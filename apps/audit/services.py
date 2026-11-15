from apps.accounts.security import client_ip

from .models import AuditLog


def log(action, user=None, request=None, target="", detail="", ip=None, username=""):
    """Write an audit entry. Never raises into the calling request."""
    try:
        if request is not None and ip is None:
            ip = client_ip(request) or None
        if user is None and request is not None and getattr(request, "user", None) and request.user.is_authenticated:
            user = request.user
        return AuditLog.objects.create(
            user=user if (user is not None and getattr(user, "pk", None)) else None,
            username=(username or (user.get_username() if user is not None and getattr(user, "pk", None) else ""))[:150],
            action=action,
            target=str(target)[:120],
            detail=str(detail)[:2000],
            ip_address=ip,
        )
    except Exception:  # pragma: no cover
        import logging

        logging.getLogger(__name__).exception("Audit log write failed")
        return None
