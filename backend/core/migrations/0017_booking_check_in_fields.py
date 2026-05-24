"""Add check-in fields and the CHECKED_IN status choice.

v10b checkin schema foundation. The `check_in_token` column lands as
NULL-able (so existing rows insert cleanly); the follow-up
`0018_backfill_check_in_token` data migration populates every existing
row with a unique token. The unique constraint is set from the start —
NULL values are allowed to coexist under Postgres's default unique
semantics (multiple NULLs do not collide).
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0016_merge_v789"),
    ]

    operations = [
        migrations.AddField(
            model_name="booking",
            name="check_in_token",
            field=models.CharField(
                blank=True,
                db_index=True,
                max_length=12,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name="booking",
            name="checked_in_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="booking",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("confirmed", "Confirmed"),
                    ("cancelled", "Cancelled"),
                    ("pending_payment", "Pending Payment"),
                    ("checked_in", "Checked in"),
                    ("completed", "Completed"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
    ]
