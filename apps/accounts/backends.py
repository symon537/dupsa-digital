from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    """Allow signing in with either the username or the e-mail address."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if not username or password is None:
            return None
        username = username.strip()
        user = User.objects.filter(username__iexact=username).first()
        if user is None and "@" in username:
            matches = list(User.objects.filter(email__iexact=username)[:2])
            user = matches[0] if len(matches) == 1 else None
        if user is None:
            User().set_password(password)  # constant-time-ish behaviour
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
