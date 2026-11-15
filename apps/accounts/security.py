"""Login rate limiting (brute-force protection) backed by Django's cache."""
from django.conf import settings
from django.core.cache import cache


def _key(username, ip):
    return f"loginfail:{(username or '').strip().lower()}:{ip}"


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded and settings.DEBUG is False and getattr(settings, "SECURE_PROXY_SSL_HEADER", None):
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def failures(username, ip):
    return cache.get(_key(username, ip), 0)


def is_locked(username, ip):
    return failures(username, ip) >= settings.LOGIN_MAX_ATTEMPTS


def register_failure(username, ip):
    key = _key(username, ip)
    cache.add(key, 0, settings.LOGIN_LOCKOUT_SECONDS)
    try:
        return cache.incr(key)
    except ValueError:  # key expired between add and incr
        cache.set(key, 1, settings.LOGIN_LOCKOUT_SECONDS)
        return 1


def clear(username, ip):
    cache.delete(_key(username, ip))
