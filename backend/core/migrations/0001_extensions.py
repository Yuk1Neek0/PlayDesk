"""
Migration 0001: Enable btree_gist and vector Postgres extensions.

Must run before the model migration that introduces the ExclusionConstraint
and the VectorField.
"""

from django.db import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies: list = []

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS btree_gist;",
            reverse_sql="DROP EXTENSION IF EXISTS btree_gist;",
        ),
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS vector;",
            reverse_sql="DROP EXTENSION IF EXISTS vector;",
        ),
    ]
