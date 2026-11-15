from django import forms

from apps.core.forms import BootstrapForm, BootstrapModelForm, DateInput

from .models import LeaveType


class LeaveApplicationForm(BootstrapForm):
    leave_type = forms.ModelChoiceField(queryset=LeaveType.objects.none())
    start_date = forms.DateField(widget=DateInput())
    end_date = forms.DateField(widget=DateInput())
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)
    document = forms.FileField(required=False, label="Supporting document (optional)")

    def __init__(self, *args, profile=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = LeaveType.objects.filter(is_active=True)
        if profile is not None:
            qs = qs.filter(gender_restriction__in=["", profile.gender])
        self.fields["leave_type"].queryset = qs

    def clean_document(self):
        doc = self.cleaned_data.get("document")
        if doc:
            if doc.size > 5 * 1024 * 1024:
                raise forms.ValidationError("File must be smaller than 5 MB.")
            if not doc.name.lower().endswith((".pdf", ".jpg", ".jpeg", ".png")):
                raise forms.ValidationError("Allowed file types: PDF, JPG, PNG.")
        return doc


class LeaveTypeForm(BootstrapModelForm):
    class Meta:
        model = LeaveType
        fields = ["name", "days_per_year", "is_paid", "requires_document", "gender_restriction", "is_active"]


class ReviewForm(BootstrapForm):
    note = forms.CharField(max_length=255, required=False, widget=forms.TextInput(attrs={"placeholder": "Optional note"}))
