"""
PlayDesk core models.

ER diagram: Store → Resource → GameMenu / Booking
            Conversation → Message
            KnowledgeChunk (RAG)
"""

from datetime import time

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.expressions import Func, Value
from django.utils.text import slugify
from pgvector.django import HnswIndex, VectorField


# ---------------------------------------------------------------------------
# Utility: tstzrange(start_time, end_time) as a DB expression
# ---------------------------------------------------------------------------
class TsTzRange(Func):
    """Wraps two datetime columns into a Postgres tstzrange."""

    function = "tstzrange"
    output_field = models.Field()


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
class Store(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=64, unique=True, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    business_hours = models.JSONField(default=dict)
    # Brand carries optional `logo_url` and `accent` (oklch override) — read
    # by the public /qr/[slug] page. Free-form so future branding fields
    # don't need a migration.
    brand = models.JSONField(default=dict, blank=True)
    points_per_booking = models.PositiveIntegerField(default=10)
    # Quiet hours are store-local (via `timezone`). The outbound sender
    # reschedules non-urgent messages that fall inside this window to the
    # next allowed boundary; urgent templates (booking_confirmation) bypass.
    quiet_hours_start = models.TimeField(default=time(22, 0))
    quiet_hours_end = models.TimeField(default=time(8, 0))

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        """Auto-fill `slug` from `name` on first save.

        Existing callers don't know about slug — including the seed
        command and every test fixture — so the field has to populate
        itself. Collisions get a `-2`, `-3`, ... suffix.
        """
        if not self.slug:
            base = slugify(self.name) or f"store-{self.pk or 'new'}"
            candidate = base
            n = 2
            qs = type(self).objects.exclude(pk=self.pk)
            while qs.filter(slug=candidate).exists():
                candidate = f"{base}-{n}"
                n += 1
            self.slug = candidate
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------
class ResourceType(models.TextChoices):
    CONSOLE = "console", "Console"
    ROOM = "room", "Room"
    TABLE = "table", "Table"


class Resource(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="resources")
    type = models.CharField(max_length=20, choices=ResourceType.choices)
    name = models.CharField(max_length=200)
    capacity = models.PositiveIntegerField(default=1)
    price_per_hour = models.DecimalField(max_digits=8, decimal_places=2)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["store", "type", "name"]

    def __str__(self) -> str:
        return f"{self.store.name} / {self.name}"


# ---------------------------------------------------------------------------
# GameMenu
# ---------------------------------------------------------------------------
class GameMenu(models.Model):
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="game_menu")
    name = models.CharField(max_length=200)
    platform = models.CharField(max_length=100)
    max_players = models.PositiveIntegerField(default=4)

    class Meta:
        ordering = ["resource", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.platform})"


# ---------------------------------------------------------------------------
# Customer + CustomerNote
# ---------------------------------------------------------------------------
class Customer(models.Model):
    """A stable identity per (store, normalized phone). Backfilled from the
    legacy customer_name / customer_phone strings on Booking. Foundational
    for retention features (visits, rewards, notes)."""

    LOCALE_CHOICES = [("en", "English"), ("zh", "中文")]

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="customers")
    phone = models.CharField(max_length=32, help_text="E.164 normalized phone number.")
    name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True, null=True)
    locale_pref = models.CharField(max_length=2, choices=LOCALE_CHOICES, default="en")
    tags = models.JSONField(default=list, blank=True)
    total_visits = models.PositiveIntegerField(default=0)
    last_visit_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-last_visit_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["store", "phone"], name="customer_unique_store_phone"),
        ]
        # NOTE: a trigram GIN index on lower(name) is a known perf follow-up
        # for >10k customer datasets. Skipped here because Django's
        # OpClass(Lower(...)) emits malformed SQL — revisit when we have a
        # dataset that justifies a raw-SQL RunSQL workaround.

    def __str__(self) -> str:
        return f"{self.name or 'Customer'} <{self.phone}>"


class CustomerNote(models.Model):
    """Free-form staff note attached to a Customer. Attribution is best-effort
    — anonymous notes are allowed for legacy/imported entries."""

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Note on {self.customer_id} ({self.created_at:%Y-%m-%d})"


# ---------------------------------------------------------------------------
# QRAction + QREvent (One QR engagement)
# ---------------------------------------------------------------------------
class QRActionKind(models.TextChoices):
    REVIEW = "review", "Google review"
    INSTAGRAM = "instagram", "Instagram"
    TIKTOK = "tiktok", "TikTok"
    REDNOTE = "rednote", "RedNote"
    WECHAT = "wechat", "WeChat"
    WIFI = "wifi", "Store WiFi"
    CUSTOM = "custom", "Custom"


class QRAction(models.Model):
    """A single chip on a store's One-QR landing page.

    Per-store ordering via `position`; unique on `(store, position)` so the
    public page render is deterministic. Reordering in admin is atomic
    (transaction-wrapped position re-write) — see api.views.
    """

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="qr_actions")
    kind = models.CharField(max_length=16, choices=QRActionKind.choices)
    label = models.CharField(max_length=80)
    target_url = models.URLField(max_length=500)
    position = models.PositiveIntegerField()
    reward_points = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["store", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["store", "position"], name="qraction_unique_store_position"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.store.name} #{self.position} – {self.label}"


class QREventKind(models.TextChoices):
    SCAN = "scan", "Scan"
    CLICK = "click", "Click"


class QREvent(models.Model):
    """A scan of the QR or a click on one of its actions.

    Scan events have ``action`` NULL (the QR itself was scanned, no
    chip was tapped). Click events carry the tapped action. The
    customer FK is optional — set when the request carries a
    pd_customer cookie that matches a real Customer.
    """

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="qr_events")
    action = models.ForeignKey(
        QRAction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="qr_events",
    )
    kind = models.CharField(max_length=8, choices=QREventKind.choices)
    user_agent = models.CharField(max_length=255, blank=True)
    locale = models.CharField(max_length=8, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["store", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.kind} on {self.action_id or 'qr'} ({self.created_at:%Y-%m-%d})"


# ---------------------------------------------------------------------------
# Conversation
# ---------------------------------------------------------------------------
class ConversationStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"
    ESCALATED = "escalated", "Escalated"


class ConversationChannel(models.TextChoices):
    """Inbound channel a conversation arrived through.

    Adapter classes in `agent/channels/` translate each channel's raw
    payload into a NormalizedMessage so the agent loop stays channel-
    agnostic.
    """

    WEB_CHAT = "web_chat", "Web chat"
    SMS = "sms", "SMS"
    WHATSAPP = "whatsapp", "WhatsApp"
    PHONE = "phone", "Phone"
    MANUAL_STAFF = "manual_staff", "Staff (manual)"


class Conversation(models.Model):
    customer_identifier = models.CharField(max_length=255)
    started_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=ConversationStatus.choices,
        default=ConversationStatus.ACTIVE,
    )
    channel = models.CharField(
        max_length=16,
        choices=ConversationChannel.choices,
        default=ConversationChannel.WEB_CHAT,
    )

    class Meta:
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"Conversation {self.pk} ({self.customer_identifier})"


# ---------------------------------------------------------------------------
# Booking
# ---------------------------------------------------------------------------
class BookingStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    CANCELLED = "cancelled", "Cancelled"
    PENDING_PAYMENT = "pending_payment", "Pending Payment"
    COMPLETED = "completed", "Completed"


class BookingSource(models.TextChoices):
    MANUAL = "manual", "Manual"
    AGENT = "agent", "Agent"


class Booking(models.Model):
    resource = models.ForeignKey(Resource, on_delete=models.PROTECT, related_name="bookings")
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookings",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bookings",
    )
    # Legacy display strings — kept for one release while the customer FK
    # is backfilled. New bookings must populate `customer` too.
    customer_name = models.CharField(max_length=200)
    customer_phone = models.CharField(max_length=50)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    status = models.CharField(
        max_length=20,
        choices=BookingStatus.choices,
        default=BookingStatus.PENDING,
    )
    source = models.CharField(
        max_length=10,
        choices=BookingSource.choices,
        default=BookingSource.MANUAL,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Prevent overlapping bookings for the same resource at the DB level.
            # Requires the btree_gist extension (enabled by a prior migration).
            # SQL equivalent:
            #   EXCLUDE USING gist
            #     (resource_id WITH =,
            #      tstzrange(start_time, end_time) WITH &&)
            ExclusionConstraint(
                name="booking_no_overlap",
                expressions=[
                    ("resource_id", RangeOperators.EQUAL),
                    (
                        TsTzRange("start_time", "end_time", Value("[)")),
                        RangeOperators.OVERLAPS,
                    ),
                ],
            ),
        ]

    def __str__(self) -> str:
        return f"Booking {self.pk} – {self.customer_name}"


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------
class MessageRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"
    TOOL = "tool", "Tool"


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=20, choices=MessageRole.choices)
    content = models.TextField(blank=True)
    tool_call_data = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Message {self.pk} [{self.role}]"


# ---------------------------------------------------------------------------
# KnowledgeChunk
# ---------------------------------------------------------------------------
class KnowledgeChunk(models.Model):
    content = models.TextField()
    embedding = VectorField(dimensions=1536)
    category = models.CharField(max_length=100)
    source = models.CharField(max_length=255)
    lang = models.CharField(max_length=10, default="en")

    class Meta:
        ordering = ["category", "source"]
        indexes = [
            # HNSW index for fast approximate nearest-neighbour search using cosine distance.
            # Requires pgvector >= 0.5.0.
            #
            # IVFFlat fallback (for older pgvector): replace HnswIndex with:
            #   IVFFlat(
            #       name="knowledge_chunk_embedding_ivfflat",
            #       fields=["embedding"],
            #       opclasses=["vector_cosine_ops"],
            #       lists=100,   # tune to sqrt(n_rows)
            #   )
            HnswIndex(
                name="knowledge_chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]

    def __str__(self) -> str:
        return f"Chunk {self.pk} [{self.category}]"


# ---------------------------------------------------------------------------
# Memberships — append-only points ledger, redeemable rewards, tier system
# ---------------------------------------------------------------------------
class PointTransactionSource(models.TextChoices):
    BOOKING = "booking", "Booking"
    QR_CLICK = "qr_click", "QR click"
    REDEMPTION = "redemption", "Redemption"
    ADJUSTMENT = "adjustment", "Adjustment"
    BACKFILL = "backfill", "Backfill"


class PointTransaction(models.Model):
    """An immutable row in the points ledger.

    Every earn / spend is one row. Current balance is ``balance_after`` on
    the latest row for the customer — denormalised for fast read, but the
    source of truth is ``SUM(delta)``. A management command asserts the
    two agree. Only written via ``core.memberships.award_points``.
    """

    customer = models.ForeignKey(
        Customer, on_delete=models.CASCADE, related_name="point_transactions"
    )
    delta = models.IntegerField()
    source = models.CharField(max_length=16, choices=PointTransactionSource.choices)
    reference = models.CharField(max_length=100, blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    balance_after = models.IntegerField()

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["customer", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"PT {self.pk} c={self.customer_id} {self.delta:+d} ({self.source})"


class Reward(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="rewards")
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    cost_points = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["store", "cost_points", "name"]
        indexes = [
            models.Index(fields=["store", "enabled"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.cost_points}pt)"


class Redemption(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="redemptions")
    reward = models.ForeignKey(Reward, on_delete=models.PROTECT, related_name="redemptions")
    transaction = models.OneToOneField(
        PointTransaction, on_delete=models.CASCADE, related_name="redemption"
    )
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    redeemed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-redeemed_at"]

    def __str__(self) -> str:
        return f"Redemption {self.pk} c={self.customer_id} r={self.reward_id}"


class RewardTier(models.Model):
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="reward_tiers")
    name = models.CharField(max_length=80)
    min_lifetime_points = models.PositiveIntegerField()
    perks_text = models.TextField(blank=True)
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ["store", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["store", "position"], name="rewardtier_unique_store_position"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.store.name} #{self.position} – {self.name}"
