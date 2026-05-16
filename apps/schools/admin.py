from django.contrib import admin

from apps.schools.models import AcademicYear, School


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "board", "current_academic_year", "created_at")
    list_filter = ("board",)
    search_fields = ("name",)


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("label", "school", "start_date", "end_date", "is_current")
    list_filter = ("is_current", "school")
    search_fields = ("label",)
