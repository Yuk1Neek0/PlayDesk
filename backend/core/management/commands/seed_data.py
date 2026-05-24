"""
Management command: seed_data

Idempotent seed for stores, resources, and game-menu items.
Safe to run multiple times — uses get_or_create / update_or_create.

v6 multi-location (epic #157, task #163): seeds TWO stores —
"PlayDesk Flagship" (slug ``playdesk-flagship``) and
"PlayDesk North · Toronto" (slug ``playdesk-north``) — so the
multi-store admin switcher + customer URL prefix have something
real to demonstrate. Existing flagship data is unchanged; the
North store gets a slimmer set of resources (2 PS5 stations + 1
private room) and the default 4 QR actions.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.memberships import award_points
from core.models import (
    Booking,
    BookingStatus,
    Customer,
    GameMenu,
    QRAction,
    Resource,
    Reward,
    Store,
)

# Each entry: (lookup-name, defaults, resources, qr_actions, game_menu).
# The slug is set explicitly so URL paths (`/s/<slug>/book`, `/qr/<slug>`)
# stay stable across slugify-grammar changes between Django versions.

FLAGSHIP_RESOURCE_DATA = [
    {
        "type": "console",
        "name": "PS5 Station 1",
        "capacity": 4,
        "price_per_hour": "60.00",
        "metadata": {"controllers": 4, "display": "55-inch 4K OLED"},
    },
    {
        "type": "console",
        "name": "PS5 Station 2",
        "capacity": 4,
        "price_per_hour": "60.00",
        "metadata": {"controllers": 4, "display": "55-inch 4K OLED"},
    },
    {
        "type": "console",
        "name": "Nintendo Switch Station",
        "capacity": 4,
        "price_per_hour": "40.00",
        "metadata": {"controllers": 4, "display": "43-inch 1080p"},
    },
    {
        "type": "room",
        "name": "Private Room A",
        "capacity": 8,
        "price_per_hour": "120.00",
        "metadata": {"consoles": ["PS5", "Switch"], "display": "65-inch 4K"},
    },
    {
        "type": "table",
        "name": "Board Game Table 1",
        "capacity": 6,
        "price_per_hour": "30.00",
        "metadata": {},
    },
]

FLAGSHIP_GAME_MENU_DATA = {
    "PS5 Station 1": [
        {"name": "FIFA 25", "platform": "PS5", "max_players": 4},
        {"name": "NBA 2K25", "platform": "PS5", "max_players": 4},
        {"name": "Call of Duty: Black Ops 6", "platform": "PS5", "max_players": 4},
    ],
    "PS5 Station 2": [
        {"name": "Gran Turismo 7", "platform": "PS5", "max_players": 2},
        {"name": "Mortal Kombat 1", "platform": "PS5", "max_players": 2},
    ],
    "Nintendo Switch Station": [
        {"name": "Mario Kart 8 Deluxe", "platform": "Switch", "max_players": 4},
        {"name": "Super Smash Bros. Ultimate", "platform": "Switch", "max_players": 4},
        {"name": "Splatoon 3", "platform": "Switch", "max_players": 4},
    ],
}

# North store — distinct name prefix so the admin switcher chips are
# visually distinguishable, and resources renamed (no name collisions
# under the unique-by-(store, name) Resource constraint anyway, but the
# distinct labels make cross-store e2e assertions easier).
NORTH_RESOURCE_DATA = [
    {
        "type": "console",
        "name": "North PS5 Station 1",
        "capacity": 4,
        "price_per_hour": "55.00",
        "metadata": {"controllers": 4, "display": "55-inch 4K OLED"},
    },
    {
        "type": "console",
        "name": "North PS5 Station 2",
        "capacity": 4,
        "price_per_hour": "55.00",
        "metadata": {"controllers": 4, "display": "55-inch 4K OLED"},
    },
    {
        "type": "room",
        "name": "North Private Room",
        "capacity": 6,
        "price_per_hour": "110.00",
        "metadata": {"consoles": ["PS5"], "display": "65-inch 4K"},
    },
]

NORTH_GAME_MENU_DATA = {
    "North PS5 Station 1": [
        {"name": "FIFA 25", "platform": "PS5", "max_players": 4},
        {"name": "EA Sports FC 25", "platform": "PS5", "max_players": 4},
    ],
    "North PS5 Station 2": [
        {"name": "Gran Turismo 7", "platform": "PS5", "max_players": 2},
    ],
}

# Default QR action set — both stores seed the same shape so the
# /qr/<slug> landing page renders the canonical 4 chips on either
# location. The (store, kind) uniqueness in `QRAction.objects.update_or_create`
# below keeps the seed idempotent per-store.
DEFAULT_QR_ACTION_DATA = [
    {
        "kind": "review",
        "label": "Leave a Google review",
        "target_url": "https://example.com/google-review-placeholder",
        "position": 0,
        "reward_points": 10,
    },
    {
        "kind": "instagram",
        "label": "Follow on Instagram",
        "target_url": "https://example.com/instagram-placeholder",
        "position": 1,
        "reward_points": 5,
    },
    {
        "kind": "wechat",
        "label": "加微信 (Add on WeChat)",
        "target_url": "https://example.com/wechat-placeholder",
        "position": 2,
        "reward_points": 5,
    },
    {
        "kind": "wifi",
        "label": "Connect to store WiFi",
        "target_url": "https://example.com/wifi-placeholder",
        "position": 3,
        "reward_points": 1,
    },
]

STORES_TO_SEED = [
    {
        "name": "PlayDesk Flagship",
        "slug": "playdesk-flagship",
        "timezone": "America/Toronto",
        "business_hours": {
            "mon": {"open": "10:00", "close": "22:00"},
            "tue": {"open": "10:00", "close": "22:00"},
            "wed": {"open": "10:00", "close": "22:00"},
            "thu": {"open": "10:00", "close": "22:00"},
            "fri": {"open": "10:00", "close": "23:00"},
            "sat": {"open": "09:00", "close": "23:00"},
            "sun": {"open": "09:00", "close": "22:00"},
        },
        "resources": FLAGSHIP_RESOURCE_DATA,
        "game_menu": FLAGSHIP_GAME_MENU_DATA,
        "qr_actions": DEFAULT_QR_ACTION_DATA,
    },
    {
        "name": "PlayDesk North · Toronto",
        "slug": "playdesk-north",
        "timezone": "America/Toronto",
        "business_hours": {
            "mon": {"open": "11:00", "close": "22:00"},
            "tue": {"open": "11:00", "close": "22:00"},
            "wed": {"open": "11:00", "close": "22:00"},
            "thu": {"open": "11:00", "close": "22:00"},
            "fri": {"open": "11:00", "close": "23:00"},
            "sat": {"open": "10:00", "close": "23:00"},
            "sun": {"open": "10:00", "close": "21:00"},
        },
        "resources": NORTH_RESOURCE_DATA,
        "game_menu": NORTH_GAME_MENU_DATA,
        "qr_actions": DEFAULT_QR_ACTION_DATA,
    },
]


class Command(BaseCommand):
    help = "Idempotently seed stores, resources, game menus, and QR actions."

    def handle(self, *args, **options) -> None:
        for store_data in STORES_TO_SEED:
            self._seed_store(store_data)
        # v7 customer-portal e2e: a stable customer-with-bookings-and-reward
        # at Flagship so customer-portal.e2e.ts can drive the full flow
        # against deterministic data.
        self._seed_customer_portal_fixture()
        # v10a staff-auth: seed a known staff login so developers and
        # Playwright can sign into /admin immediately after a fresh boot.
        self._seed_demo_staff_user()
        # v11a rotating-checkin: seed a customer with two same-day bookings
        # (different resources) so rotating-checkin.e2e.ts can drive the
        # disambiguation flow + ensure there's at least one active rotating
        # key for the door display.
        self._seed_rotating_checkin_fixture()
        # v11c retention-scoring: seed cohort fixtures so the admin
        # /customers page has dormant + opt-out rows for the e2e test to
        # drive. Runs the sweeper at the end to populate cohort labels
        # deterministically from last_visit_at without needing a separate
        # cron invocation in CI. Must run AFTER all other seeders so the
        # sweeper sees a fully-populated customer table.
        self._seed_retention_fixtures()
        self.stdout.write(self.style.SUCCESS("Seed complete."))

    def _seed_rotating_checkin_fixture(self) -> None:
        """Seed a same-day double-booked customer + ensure a fresh rotating key.

        Idempotent: re-running may add fresh bookings only if no upcoming
        ones exist for the e2e customer, and minting only happens via the
        services helper (no duplication on re-seed).
        """
        from checkin.services import get_active_key, mint_key

        flagship = Store.objects.filter(slug="playdesk-flagship").first()
        if flagship is None:
            return

        rc_customer, _ = Customer.objects.update_or_create(
            store=flagship,
            phone="+15557654321",
            defaults={"name": "Rotating Checkin Customer"},
        )

        # Two resources at Flagship — distinct so the per-resource overlap
        # constraint never fires. Skip if the customer already has
        # upcoming bookings (idempotent re-seed).
        upcoming = Booking.objects.filter(
            customer=rc_customer,
            start_time__gt=timezone.now() - timedelta(hours=1),
        ).count()
        if upcoming < 2:
            resources = list(flagship.resources.order_by("id")[:2])
            now = timezone.now()
            # 30 min from now + 90 min from now — both inside the +/-2hr window.
            for offset_min, res in zip([30, 90], resources):
                start = now + timedelta(minutes=offset_min)
                try:
                    Booking.objects.create(
                        resource=res,
                        customer=rc_customer,
                        customer_name=rc_customer.name,
                        customer_phone=rc_customer.phone,
                        start_time=start,
                        end_time=start + timedelta(hours=1),
                        status=BookingStatus.CONFIRMED,
                    )
                except Exception:
                    # Overlap with another resource booking — skip silently
                    # so re-seeding stays idempotent.
                    pass

        # Ensure a rotating key exists for both seeded stores so the admin
        # display page works immediately after boot.
        for store in Store.objects.all():
            if get_active_key(store) is None:
                mint_key(store)

    def _seed_demo_staff_user(self) -> None:
        """Idempotently create the `playdesk_staff` demo user (v10a).

        Password is intentionally well-known so the disclosure is the
        seed log line — operators rotate it before any non-dev deploy.
        """
        from django.contrib.auth import get_user_model

        User = get_user_model()
        username = "playdesk_staff"
        password = "playdesk_staff_demo_pw"
        user, created = User.objects.get_or_create(
            username=username,
            defaults={"is_staff": True, "is_active": True},
        )
        if created:
            user.set_password(password)
            user.is_staff = True
            user.is_active = True
            user.save()
        self.stdout.write(f"Demo staff: username={username} password={password}")

    def _seed_customer_portal_fixture(self) -> None:
        flagship = Store.objects.filter(slug="playdesk-flagship").first()
        if flagship is None:
            return

        e2e_customer, _ = Customer.objects.update_or_create(
            store=flagship,
            phone="+15551234567",
            defaults={"name": "E2E Customer"},
        )

        # Two upcoming bookings — pick a resource at Flagship for both.
        # Idempotent: if the customer already has >=2 upcoming bookings,
        # leave them alone (avoids the GIST overlap constraint firing on
        # a re-seed against a shifted `now()`).
        resource = flagship.resources.order_by("id").first()
        if resource is not None:
            existing_upcoming = Booking.objects.filter(
                customer=e2e_customer,
                start_time__gt=timezone.now(),
            ).count()
            if existing_upcoming < 2:
                now = timezone.now()
                for offset_h, length_h in [(48, 2), (96, 2)]:
                    start = now + timedelta(hours=offset_h)
                    try:
                        Booking.objects.create(
                            resource=resource,
                            customer=e2e_customer,
                            customer_name=e2e_customer.name,
                            customer_phone=e2e_customer.phone,
                            start_time=start,
                            end_time=start + timedelta(hours=length_h),
                            status=BookingStatus.CONFIRMED,
                        )
                    except Exception:
                        # Overlap with another booking — silently skip
                        # so re-seeding stays idempotent.
                        pass

        # An affordable reward (5 pts) the customer can redeem in the e2e test.
        Reward.objects.update_or_create(
            store=flagship,
            name="E2E reward",
            defaults={"cost_points": 5, "enabled": True, "description": "Test reward"},
        )

        # Seed enough points so the e2e test can redeem it. Use a fixed
        # reference so re-seeding doesn't double-credit.
        from core.models import PointTransaction

        if not PointTransaction.objects.filter(
            customer=e2e_customer, reference="e2e-seed"
        ).exists():
            award_points(e2e_customer, 100, "adjustment", reference="e2e-seed")

    def _seed_retention_fixtures(self) -> None:
        """Seed Flagship cohort customers + run the sweeper (v11c).

        Builds 9 customers across the cohort spectrum so the admin
        /customers page has a dormant population (incl. one with
        sms_opt_out) for retention.e2e.ts to drive. Idempotent: re-runs
        update last_visit_at against `now()` and re-derive cohort.
        """
        from django.core.management import call_command

        flagship = Store.objects.filter(slug="playdesk-flagship").first()
        if flagship is None:
            return

        now = timezone.now()
        # (phone-suffix, name, visits, days-since-last-visit, tags)
        # Spread across cohorts. Phones use a unique prefix so they
        # don't collide with the customer-portal fixture (+1555123____)
        # or any user-created bookings.
        fixtures = [
            ("4400001", "Retention Active A", 5, 5, []),
            ("4400002", "Retention Active B", 3, 12, []),
            ("4400003", "Retention At-risk A", 6, 40, []),
            ("4400004", "Retention At-risk B", 4, 50, []),
            ("4400005", "Retention Dormant A", 8, 70, []),
            ("4400006", "Retention Dormant B", 6, 80, []),
            ("4400007", "Retention Dormant OptOut", 7, 75, ["sms_opt_out"]),
            ("4400008", "Retention Lost", 4, 120, []),
            ("4400009", "Retention New", 0, None, []),
        ]
        for suffix, name, visits, days_ago, tags in fixtures:
            phone = f"+1416{suffix}"
            last_visit_at = now - timedelta(days=days_ago) if days_ago is not None else None
            Customer.objects.update_or_create(
                store=flagship,
                phone=phone,
                defaults={
                    "name": name,
                    "total_visits": visits,
                    "last_visit_at": last_visit_at,
                    "tags": tags,
                },
            )

        # Derive cohort + churn_score from the freshly-seeded last_visit_at.
        # Scoped to flagship so other-store data stays stable across reseeds.
        call_command("recompute_retention", store=flagship.slug)

    def _seed_store(self, data: dict) -> None:
        # update_or_create on the explicit slug — slug is unique, so this is
        # the safest idempotency key. The name is kept in `defaults` so a
        # display-name change in this file lands on re-run.
        store, created = Store.objects.update_or_create(
            slug=data["slug"],
            defaults={
                "name": data["name"],
                "timezone": data["timezone"],
                "business_hours": data["business_hours"],
            },
        )
        self.stdout.write(f"Store: {'created' if created else 'updated'} — {store.name}")

        for res_data in data["resources"]:
            resource, r_created = Resource.objects.update_or_create(
                store=store,
                name=res_data["name"],
                defaults={
                    "type": res_data["type"],
                    "capacity": res_data["capacity"],
                    "price_per_hour": res_data["price_per_hour"],
                    "metadata": res_data["metadata"],
                },
            )
            self.stdout.write(
                f"  Resource: {'created' if r_created else 'updated'} — {resource.name}"
            )

            for game_data in data["game_menu"].get(resource.name, []):
                game, g_created = GameMenu.objects.update_or_create(
                    resource=resource,
                    name=game_data["name"],
                    defaults={
                        "platform": game_data["platform"],
                        "max_players": game_data["max_players"],
                    },
                )
                self.stdout.write(
                    f"    Game: {'created' if g_created else 'updated'} — {game.name}"
                )

        # QR actions — idempotent on (store, kind), so re-running the seed
        # never duplicates the chip set. Position is taken from the seed
        # data to keep the configured order stable.
        for qr in data["qr_actions"]:
            action, qr_created = QRAction.objects.update_or_create(
                store=store,
                kind=qr["kind"],
                defaults={
                    "label": qr["label"],
                    "target_url": qr["target_url"],
                    "position": qr["position"],
                    "reward_points": qr["reward_points"],
                    "enabled": True,
                },
            )
            self.stdout.write(
                f"  QR action: {'created' if qr_created else 'updated'} — {action.label}"
            )
