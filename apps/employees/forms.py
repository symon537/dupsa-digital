import re
import secrets
import string

from django import forms
from django.contrib.auth import password_validation

from apps.accounts.models import Role, User
from apps.core.forms import DateInput, style_fields

from .models import EmployeeProfile


def generate_password(length=10):
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
            return pw


class EmployeeForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    email = forms.EmailField(required=False)
    username = forms.CharField(max_length=150, required=False, help_text="Leave blank to generate from the name.")
    password = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to generate a temporary password (shown once after saving).",
    )

    class Meta:
        model = EmployeeProfile
        fields = ["gender", "phone", "address", "photo", "department", "position", "branch", "allowed_branches",
                  "supervisor", "employment_date", "status", "emergency_contact_name", "emergency_contact_phone"]
        widgets = {"employment_date": DateInput(), "allowed_branches": forms.SelectMultiple(attrs={"size": 4})}

    field_order = ["first_name", "last_name", "username", "email", "password", "gender", "phone", "address", "photo",
                   "department", "position", "branch", "allowed_branches", "supervisor", "employment_date", "status",
                   "emergency_contact_name", "emergency_contact_phone"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.branches.models import Branch
        from apps.departments.models import Department, Position

        self.fields["branch"].queryset = Branch.objects.filter(is_active=True) | Branch.objects.filter(pk=self.instance.branch_id or 0)
        self.fields["department"].queryset = Department.objects.filter(is_active=True)
        self.fields["position"].queryset = Position.objects.filter(is_active=True)
        self.fields["supervisor"].queryset = User.objects.filter(is_active=True).exclude(role=Role.EMPLOYEE)
        self.fields["allowed_branches"].queryset = Branch.objects.filter(is_active=True)
        if self.instance.pk:
            u = self.instance.user
            self.fields["first_name"].initial = u.first_name
            self.fields["last_name"].initial = u.last_name
            self.fields["email"].initial = u.email
            self.fields["username"].initial = u.username
            self.fields["username"].disabled = True
            self.fields["password"].help_text = "Leave blank to keep the current password."
        style_fields(self)

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        qs = User.objects.filter(email__iexact=email) if email else User.objects.none()
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise forms.ValidationError("Another user already uses this e-mail address.")
        return email

    def clean_username(self):
        name = (self.cleaned_data.get("username") or "").strip()
        if self.instance.pk:
            return self.instance.user.username
        if name and User.objects.filter(username__iexact=name).exists():
            raise forms.ValidationError("This username is taken.")
        return name

    def clean_password(self):
        pw = self.cleaned_data.get("password")
        if pw:
            password_validation.validate_password(pw)
        return pw

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        if photo and hasattr(photo, "size") and photo.size > 3 * 1024 * 1024:
            raise forms.ValidationError("Photo must be smaller than 3 MB.")
        return photo

    def _unique_username(self):
        d = self.cleaned_data
        base = re.sub(r"[^a-z0-9.]", "", f"{d['first_name']}.{d['last_name']}".lower()) or "employee"
        name, i = base, 1
        while User.objects.filter(username__iexact=name).exists():
            i += 1
            name = f"{base}{i}"
        return name

    def save(self, commit=True):
        d = self.cleaned_data
        self.temp_password = None
        profile = super().save(commit=False)
        if profile.pk:
            user = profile.user
        else:
            user = User(username=d.get("username") or self._unique_username(), role=Role.EMPLOYEE)
        user.first_name, user.last_name, user.email = d["first_name"], d["last_name"], d.get("email", "")
        user.phone = d.get("phone", "")
        if d.get("password"):
            user.set_password(d["password"])
        elif not user.pk:
            self.temp_password = generate_password()
            user.set_password(self.temp_password)
        from .models import ACTIVE_STATUSES

        user.is_active = profile.status in ACTIVE_STATUSES  # keep login access in step with employment status
        user.save()
        profile.user = user
        profile.save()
        self.save_m2m()
        return profile
