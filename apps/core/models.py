"""Base models and managers for tenant-scoped data."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models
from django.utils import timezone

from .context import get_current_school_id

if TYPE_CHECKING:
    pass


class TenantManager(models.Manager):
    """Default manager that:

    1. Filters out soft-deleted rows (``deleted_at IS NULL``).
    2. Scopes every queryset to the school in the request context.

    If no school is set on the context, returns an empty queryset (fail closed).
    """

    def get_queryset(self) -> models.QuerySet:
        qs = super().get_queryset().filter(deleted_at__isnull=True)
        school_id = get_current_school_id()
        if school_id is None:
            return qs.none()
        return qs.filter(school_id=school_id)

    def all_tenants(self) -> models.QuerySet:
        """Bypass the tenant filter. Use sparingly: admin scripts, Celery
        system jobs, signup flows. Still filters soft-deleted rows."""
        return super().get_queryset().filter(deleted_at__isnull=True)

    def including_deleted(self) -> models.QuerySet:
        """Bypass both filters. Use only for explicit recovery/audit code."""
        return super().get_queryset()


class TenantScopedModel(models.Model):
    """Abstract base for every model that belongs to a school."""

    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        related_name="+",
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = TenantManager()

    class Meta:
        abstract = True

    def soft_delete(self) -> None:
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])

    def restore(self) -> None:
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])
