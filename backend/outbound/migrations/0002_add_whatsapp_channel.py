"""Add `whatsapp` to OutboundMessage.channel choices.

The underlying column is a varchar so no DDL is required, but Django
tracks `choices` in migrations and the test runner asserts the model
state matches. This migration only updates the choices metadata.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("outbound", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="outboundmessage",
            name="channel",
            field=models.CharField(
                choices=[
                    ("sms", "SMS"),
                    ("whatsapp", "WhatsApp"),
                    ("web_chat", "Web chat"),
                ],
                default="sms",
                max_length=16,
            ),
        ),
    ]
