from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("", include("apps.accounts.urls")),
    path("employees/", include("apps.employees.urls")),
    path("departments/", include("apps.departments.urls")),
    path("branches/", include("apps.branches.urls")),
    path("shifts/", include("apps.shifts.urls")),
    path("attendance/", include("apps.attendance.urls")),
    path("leaves/", include("apps.leaves.urls")),
    path("reports/", include("apps.reports.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("audit/", include("apps.audit.urls")),
    path("my/", include("apps.attendance.my_urls")),
    path("api/", include("apps.attendance.api_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = "apps.core.views.permission_denied"
