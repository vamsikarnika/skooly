from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import OneTimePassword, PasswordResetToken, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("phone", "first_name", "last_name", "school", "role", "is_active")
    list_filter = ("role", "is_active", "school")
    search_fields = ("phone", "email", "first_name", "last_name")
    ordering = ("-created_at",)
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("Identity", {"fields": ("first_name", "last_name", "email")}),
        ("Tenant & role", {"fields": ("school", "role")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Timestamps", {"fields": ("last_login_at", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone", "password1", "password2", "first_name", "school", "role"),
            },
        ),
    )
    readonly_fields = ("created_at", "updated_at", "last_login_at")


admin.site.register(PasswordResetToken)
admin.site.register(OneTimePassword)
