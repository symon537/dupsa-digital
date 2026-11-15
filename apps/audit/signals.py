from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .services import log


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    log("auth.login", user=user, request=request, detail="Signed in")


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        log("auth.logout", user=user, request=request, detail="Signed out")


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    name = (credentials or {}).get("username", "")
    log("auth.login_failed", request=request, username=name, detail=f"Failed sign-in for '{name}'")
