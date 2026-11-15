from datetime import timedelta

from django import forms
from django.utils import timezone

from apps.core.forms import BootstrapModelForm, DateInput, TimeInput

from .models import AttendanceCorrection


class CorrectionForm(BootstrapModelForm):
    class Meta:
        model = AttendanceCorrection
        fields = ["date", "requested_clock_in", "requested_clock_out", "reason"]
        widgets = {"date": DateInput(), "requested_clock_in": TimeInput(), "requested_clock_out": TimeInput(),
                   "reason": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.profile = profile

    def clean_date(self):
        d = self.cleaned_data["date"]
        today = timezone.localdate()
        if d > today:
            raise forms.ValidationError("You cannot correct a future date.")
        if d < today - timedelta(days=31):
            raise forms.ValidationError("Corrections older than 31 days must be handled by HR directly.")
        return d

    def clean(self):
        data = super().clean()
        cin, cout = data.get("requested_clock_in"), data.get("requested_clock_out")
        if not cin and not cout:
            raise forms.ValidationError("Enter the corrected clock-in time, clock-out time, or both.")
        if cin and cout and cout <= cin:
            self.add_error("requested_clock_out", "Clock-out must be after clock-in.")
        if self.profile and data.get("date") and AttendanceCorrection.objects.filter(
            employee=self.profile, date=data["date"], status="pending"
        ).exists():
            raise forms.ValidationError("You already have a pending correction for this date.")
        return data
