from django import forms
from django.conf import settings as dj_settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Role
from apps.accounts.permissions import MANAGE_SETTINGS, MANAGE_ORG, VIEW_STAFF, role_required
from apps.attendance import analytics
from apps.audit.services import log

from .models import WEEKDAY_CHOICES, CompanySettings, Holiday, parse_days

DASHBOARD_TITLES = {
    Role.SUPER_ADMIN: "HR Admin Dashboard",
    Role.HR_MANAGER: "HR Admin Dashboard",
    Role.DIRECTOR: "Director Dashboard",
    Role.BRANCH_MANAGER: "Branch Manager Dashboard",
    Role.SUPERVISOR: "Supervisor Dashboard",
}


@login_required
def home(request):
    """Staff roles see the analytical dashboard; employees go to the mobile dashboard."""
    user = request.user
    if user.role not in VIEW_STAFF:
        return redirect("my:home")
    return render(request, "dashboard/staff.html", {
        "title": DASHBOARD_TITLES.get(user.role, "Dashboard"),
        "stats": analytics.dashboard_stats(user),
        "recent": analytics.recent_clock_ins(user),
        "today": timezone.localdate(),
    })


@role_required(Role.SUPER_ADMIN)
def about(request):
    return render(request, "core/about.html", {
        "developer_name": dj_settings.DEVELOPER_NAME,
        "developer_email": dj_settings.DEVELOPER_EMAIL,
    })


class SettingsForm(forms.ModelForm):
    working_days_list = forms.MultipleChoiceField(
        choices=WEEKDAY_CHOICES, widget=forms.CheckboxSelectMultiple, label="Default working days"
    )

    class Meta:
        model = CompanySettings
        fields = ["company_name", "enforce_gps", "max_gps_accuracy_m", "overtime_threshold_minutes",
                  "qr_validity_days", "login_background_enabled", "login_background"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["working_days_list"].initial = [str(d) for d in parse_days(self.instance.working_days)]
        for name, f in self.fields.items():
            if isinstance(f.widget, forms.CheckboxInput):
                f.widget.attrs["class"] = "form-check-input"
            elif not isinstance(f.widget, forms.CheckboxSelectMultiple):
                f.widget.attrs["class"] = "form-control"

    def clean_login_background(self):
        img = self.cleaned_data.get("login_background")
        if img and hasattr(img, "size") and img.size > 3 * 1024 * 1024:
            raise forms.ValidationError("Image must be smaller than 3 MB.")
        return img

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.working_days = ",".join(sorted(self.cleaned_data["working_days_list"]))
        if commit:
            obj.save()
        return obj


@role_required(*MANAGE_SETTINGS)
def settings_view(request):
    form = SettingsForm(request.POST or None, request.FILES or None, instance=CompanySettings.get())
    if request.method == "POST" and form.is_valid():
        form.save()
        log("settings.updated", request=request, detail="Company settings changed")
        messages.success(request, "Settings saved.")
        return redirect("core:settings")
    return render(request, "core/settings.html", {"form": form})


class HolidayForm(forms.ModelForm):
    class Meta:
        model = Holiday
        fields = ["date", "name", "branch"]
        widgets = {"date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
                   "name": forms.TextInput(attrs={"class": "form-control"}),
                   "branch": forms.Select(attrs={"class": "form-select"})}

    def validate_unique(self):  # handles the (date, branch=NULL) case that DB constraints ignore
        super().validate_unique()
        d, b = self.cleaned_data.get("date"), self.cleaned_data.get("branch")
        if d and Holiday.objects.filter(date=d, branch=b).exists():
            self.add_error("date", "A holiday already exists for this date.")


@role_required(*MANAGE_ORG)
def holidays(request):
    form = HolidayForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        h = form.save()
        log("holiday.created", request=request, target=h.name, detail=str(h.date))
        messages.success(request, "Holiday added.")
        return redirect("core:holidays")
    return render(request, "core/holidays.html", {"form": form, "holidays": Holiday.objects.select_related("branch")})


@role_required(*MANAGE_ORG)
@require_POST
def holiday_delete(request, pk):
    h = get_object_or_404(Holiday, pk=pk)
    log("holiday.deleted", request=request, target=h.name, detail=str(h.date))
    h.delete()
    messages.success(request, "Holiday removed.")
    return redirect("core:holidays")


def permission_denied(request, exception=None):
    return render(request, "403.html", status=403)
