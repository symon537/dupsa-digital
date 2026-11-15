from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from .models import Role, User


class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Username / Email",
        widget=forms.TextInput(attrs={"placeholder": "Enter your username or email", "autocomplete": "username", "autofocus": True}),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"placeholder": "Enter your password", "autocomplete": "current-password"}),
    )
    remember_me = forms.BooleanField(required=False, label="Remember me")
    error_messages = {
        "invalid_login": "Incorrect username/email or password. Please try again.",
        "inactive": "This account is deactivated. Please contact HR.",
    }


class UserForm(forms.ModelForm):
    password = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False), label="Password",
        help_text="Leave blank to keep the current password.",
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "phone", "role", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if not isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.setdefault("class", "form-control")
        self.fields["role"].widget.attrs["class"] = "form-select"
        self.fields["is_active"].widget.attrs["class"] = "form-check-input"
        if self.instance.pk is None:
            self.fields["password"].required = True
            self.fields["password"].help_text = "Minimum 8 characters."

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another user already uses this e-mail address.")
        return email

    def clean_password(self):
        pw = self.cleaned_data.get("password")
        if pw:
            password_validation.validate_password(pw, self.instance)
        return pw

    def save(self, commit=True):
        user = super().save(commit=False)
        pw = self.cleaned_data.get("password")
        if pw:
            user.set_password(pw)
        if commit:
            user.save()
        return user
