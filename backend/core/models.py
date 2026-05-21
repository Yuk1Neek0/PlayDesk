"""
PlayDesk core models.

ER diagram: Store → Resource → GameMenu / Booking
            Conversation → Message
            KnowledgeChunk (RAG)
"""

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.db import models
from django.db.models.expressions import Func, Value
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
    timezone = models.CharField(max_length=64, default="UTC")
    business_hours = models.JSONField(default=dict)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


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
# Conversation
# ---------------------------------------------------------------------------
class ConversationStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"
    ESCALATED = "escalated", "Escalated"


class Conversation(models.Model):
    customer_identifier = models.CharField(max_length=255)
    started_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=ConversationStatus.choices,
        default=ConversationStatus.ACTIVE,
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
