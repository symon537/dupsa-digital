from django.conf import settings


def branding(request):
    """Variables available in every template (brand, settings, unread notifications)."""
    from .models import CompanySettings

    ctx = {"SITE_NAME": "Malkia Konnect", "APP_NAME": "Smart Attendance Management System"}
    try:
        company = CompanySettings.get()
    except Exception:  # database not migrated yet
        return ctx
    ctx["company"] = company
    ctx["login_bg_url"] = (
        (company.login_background.url if company.login_background else f"{settings.STATIC_URL}images/login-bg-director.jpg")
        if company.login_background_enabled
        else ""
    )
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from apps.notifications.models import Notification

        ctx["unread_count"] = Notification.objects.filter(user=user, is_read=False).count()
    return ctx
