"""
Migration 0002: Create all PlayDesk core tables.

Depends on 0001_extensions so btree_gist and vector are already available.
"""

import django.db.models.deletion
import django.db.models.expressions
import pgvector.django
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.db import migrations, models

import core.models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_extensions"),
    ]

    operations = [
        # Store
        migrations.CreateModel(
            name="Store",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200)),
                ("timezone", models.CharField(default="UTC", max_length=64)),
                ("business_hours", models.JSONField(default=dict)),
            ],
            options={"ordering": ["name"]},
        ),
        # Resource
        migrations.CreateModel(
            name="Resource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "store",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="resources",
                        to="core.store",
                    ),
                ),
                (
                    "type",
                    models.CharField(
                        choices=[("console", "Console"), ("room", "Room"), ("table", "Table")],
                        max_length=20,
                    ),
                ),
                ("name", models.CharField(max_length=200)),
                ("capacity", models.PositiveIntegerField(default=1)),
                ("price_per_hour", models.DecimalField(decimal_places=2, max_digits=8)),
                ("metadata", models.JSONField(blank=True, default=dict)),
            ],
            options={"ordering": ["store", "type", "name"]},
        ),
        # GameMenu
        migrations.CreateModel(
            name="GameMenu",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "resource",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="game_menu",
                        to="core.resource",
                    ),
                ),
                ("name", models.CharField(max_length=200)),
                ("platform", models.CharField(max_length=100)),
                ("max_players", models.PositiveIntegerField(default=4)),
            ],
            options={"ordering": ["resource", "name"]},
        ),
        # Conversation
        migrations.CreateModel(
            name="Conversation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("customer_identifier", models.CharField(max_length=255)),
                ("started_at", models.DateTimeField(auto_now_add=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("closed", "Closed"),
                            ("escalated", "Escalated"),
                        ],
                        default="active",
                        max_length=20,
                    ),
                ),
            ],
            options={"ordering": ["-started_at"]},
        ),
        # Booking
        migrations.CreateModel(
            name="Booking",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "resource",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bookings",
                        to="core.resource",
                    ),
                ),
                (
                    "conversation",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="bookings",
                        to="core.conversation",
                    ),
                ),
                ("customer_name", models.CharField(max_length=200)),
                ("customer_phone", models.CharField(max_length=50)),
                ("start_time", models.DateTimeField()),
                ("end_time", models.DateTimeField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending"),
                            ("confirmed", "Confirmed"),
                            ("cancelled", "Cancelled"),
                            ("pending_payment", "Pending Payment"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[("manual", "Manual"), ("agent", "Agent")],
                        default="manual",
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        # Message
        migrations.CreateModel(
            name="Message",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "conversation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="messages",
                        to="core.conversation",
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("user", "User"),
                            ("assistant", "Assistant"),
                            ("tool", "Tool"),
                        ],
                        max_length=20,
                    ),
                ),
                ("content", models.TextField(blank=True)),
                ("tool_call_data", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["created_at"]},
        ),
        # KnowledgeChunk
        migrations.CreateModel(
            name="KnowledgeChunk",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("content", models.TextField()),
                ("embedding", pgvector.django.VectorField(dimensions=1536)),
                ("category", models.CharField(max_length=100)),
                ("source", models.CharField(max_length=255)),
                ("lang", models.CharField(default="en", max_length=10)),
            ],
            options={"ordering": ["category", "source"]},
        ),
        # ExclusionConstraint on Booking (requires btree_gist from 0001)
        migrations.AddConstraint(
            model_name="booking",
            constraint=ExclusionConstraint(
                expressions=[
                    ("resource_id", RangeOperators.EQUAL),
                    (
                        core.models.TsTzRange(
                            "start_time",
                            "end_time",
                            django.db.models.expressions.Value("[)"),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                name="booking_no_overlap",
            ),
        ),
    ]
