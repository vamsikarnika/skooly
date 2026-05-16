"""School and AcademicYear — the top-level tenant entities.

School itself is NOT tenant-scoped (it IS the tenant). AcademicYear is tied
to a school but uses the standard manager (we filter by school manually since
TenantScopedModel would create an infinite-loop on the school FK).
"""

from __future__ import annotations

from django.db import models


class Board(models.TextChoices):
    AP_STATE = "AP_STATE", "AP State Board"
    CBSE = "CBSE", "CBSE"
    ICSE = "ICSE", "ICSE"
    OTHER = "OTHER", "Other"


class SchoolQuerySet(models.QuerySet):
    def active(self) -> SchoolQuerySet:
        return self.filter(deleted_at__isnull=True)


class SchoolManager(models.Manager):
    def get_queryset(self) -> SchoolQuerySet:
        return SchoolQuerySet(self.model, using=self._db).filter(deleted_at__isnull=True)


class School(models.Model):
    name = models.CharField(max_length=200)
    board = models.CharField(max_length=20, choices=Board.choices, default=Board.AP_STATE)
    address = models.TextField(blank=True)
    logo_url = models.URLField(blank=True)
    whatsapp_number = models.CharField(max_length=20, blank=True)
    whatsapp_bsp_config = models.JSONField(default=dict, blank=True)
    primary_color = models.CharField(max_length=20, default="#2563eb")

    current_academic_year = models.ForeignKey(
        "schools.AcademicYear",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = SchoolManager()
    all_tenants = models.Manager()

    class Meta:
        db_table = "schools"

    def __str__(self) -> str:
        return self.name


class AcademicYear(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="academic_years")
    label = models.CharField(max_length=20, help_text="e.g. '2025-26'")
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "academic_years"
        unique_together = [("school", "label")]
        ordering = ["-start_date"]

    def __str__(self) -> str:
        return f"{self.school.name} — {self.label}"
