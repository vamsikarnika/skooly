"""Helpers for Postgres Row-Level Security.

RLS is defence-in-depth on top of the TenantManager. It enforces tenant
isolation at the database layer using a per-connection GUC
(``app.current_school_id``) that the middleware sets on every request.

Use in migrations like::

    from django.db import migrations
    from apps.core.rls import enable_rls_sql

    class Migration(migrations.Migration):
        dependencies = [...]
        operations = [
            migrations.RunSQL(*enable_rls_sql("students")),
        ]
"""

from __future__ import annotations


def enable_rls_sql(table_name: str, school_column: str = "school_id") -> tuple[str, str]:
    """Return (forward, reverse) SQL pair to enable/disable RLS on a table."""
    forward = f"""
        ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON {table_name};
        CREATE POLICY tenant_isolation ON {table_name}
            USING ({school_column}::text = current_setting('app.current_school_id', true))
            WITH CHECK ({school_column}::text = current_setting('app.current_school_id', true));
    """
    reverse = f"""
        DROP POLICY IF EXISTS tenant_isolation ON {table_name};
        ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY;
    """
    return forward, reverse
