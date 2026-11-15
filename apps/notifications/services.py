"""Create in-app notifications.

``deliver_external`` is the single hook where e-mail / SMS gateways can be plugged in later.
"""
import logging

from .models import Notification

logger = logging.getLogger(__name__)


def deliver_external(notification):  # pragma: no cover - placeholder for future channels
    """Future: send e-mail (SMTP) or SMS (Tanzanian gateway) for this notification."""
    return None


def notify(user, title, message="", category=Notification.Category.SYSTEM, link=""):
    if user is None or not user.is_active:
        return None
    n = Notification.objects.create(user=user, title=title[:120], message=message[:400], category=category, link=link)
    try:
        deliver_external(n)
    except Exception:  # never let a delivery problem break attendance
        logger.exception("External notification delivery failed")
    return n


def notify_many(users, title, message="", category=Notification.Category.SYSTEM, link=""):
    seen = set()
    for u in users:
        if u is not None and u.pk not in seen:
            seen.add(u.pk)
            notify(u, title, message, category, link)
    return len(seen)


def managers_of(profile):
    """Users who should hear about an employee: branch manager and supervisor."""
    users = []
    if profile.branch.manager_id:
        users.append(profile.branch.manager)
    if profile.supervisor_id:
        users.append(profile.supervisor)
    return users


def hr_users():
    from apps.accounts.models import Role, User

    return User.objects.filter(role__in=[Role.HR_MANAGER, Role.SUPER_ADMIN], is_active=True)
