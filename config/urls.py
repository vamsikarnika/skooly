"""Root URL configuration."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from config.api import api, parent_api, teacher_api

urlpatterns = [
    path("admin/", admin.site.urls),
    # The teacher and parent APIs must be listed before the admin "api/v1/"
    # prefix, otherwise the broader prefix would swallow their sub-paths and
    # 404 inside the admin api.
    path("api/v1/teacher/", teacher_api.urls),
    path("api/v1/parent/", parent_api.urls),
    path("api/v1/", api.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
