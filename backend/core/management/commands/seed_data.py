"""
Management command: seed_data

Idempotent seed for stores, resources, and game-menu items.
Safe to run multiple times — uses get_or_create / update_or_create.
"""

from django.core.management.base import BaseCommand

from core.models import GameMenu, QRAction, Resource, Store

STORE_DATA = {
    "name": "PlayDesk Flagship",
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
}

RESOURCE_DATA = [
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

QR_ACTION_DATA = [
    # Highest-value action (review) leads, then social follows, then WiFi.
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


GAME_MENU_DATA = {
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


class Command(BaseCommand):
    help = "Idempotently seed store, resource, and game-menu data."

    def handle(self, *args, **options) -> None:
        store, created = Store.objects.update_or_create(
            name=STORE_DATA["name"],
            defaults={
                "timezone": STORE_DATA["timezone"],
                "business_hours": STORE_DATA["business_hours"],
            },
        )
        self.stdout.write(f"Store: {'created' if created else 'updated'} — {store.name}")

        for res_data in RESOURCE_DATA:
            resource, created = Resource.objects.update_or_create(
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
                f"  Resource: {'created' if created else 'updated'} — {resource.name}"
            )

            for game_data in GAME_MENU_DATA.get(resource.name, []):
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
        for qr in QR_ACTION_DATA:
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

        self.stdout.write(self.style.SUCCESS("Seed complete."))
