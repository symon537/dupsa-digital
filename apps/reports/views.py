from datetime import date

from django import forms
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.permissions import VIEW_REPORTS, role_required, visible_branches, visible_employees
from apps.audit.services import log
from apps.core.forms import BootstrapForm, DateInput
from apps.departments.models import Department

from . import exports
from .builders import REPORT_TYPES, build_report

MAX_PREVIEW_ROWS = 500


class ReportForm(BootstrapForm):
    type = forms.ChoiceField(choices=REPORT_TYPES, label="Report")
    date_from = forms.DateField(widget=DateInput(), label="From / reference date")
    date_to = forms.DateField(widget=DateInput(), required=False, label="To")
    branch = forms.ModelChoiceField(queryset=None, required=False, empty_label="All branches")
    department = forms.ModelChoiceField(queryset=Department.objects.all(), required=False, empty_label="All departments")
    employee = forms.ModelChoiceField(queryset=None, required=False, empty_label="All employees")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = visible_branches(user)
        emp = visible_employees(user).order_by("employee_number")
        self.fields["employee"].queryset = emp
        self.fields["employee"].label_from_instance = lambda e: f"{e.employee_number} - {e.full_name}"

    def clean(self):
        data = super().clean()
        if data.get("date_from") and data.get("date_to") and data["date_to"] < data["date_from"]:
            self.add_error("date_to", "The end date cannot be before the start date.")
        if data.get("type") == "employee" and not data.get("employee"):
            self.add_error("employee", "Select an employee for the employee report.")
        return data


@role_required(*VIEW_REPORTS)
def report_view(request):
    today = timezone.localdate()
    initial = {"type": "daily", "date_from": today}
    form = ReportForm(request.GET or initial, user=request.user)
    report = None
    if request.GET and form.is_valid():
        d = form.cleaned_data
        report = build_report(
            request.user, d["type"], d["date_from"], d.get("date_to") or d["date_from"],
            branch=d["branch"].pk if d.get("branch") else None,
            department=d["department"].pk if d.get("department") else None,
            employee=d["employee"].pk if d.get("employee") else None,
        )
        fmt = request.GET.get("format", "")
        if fmt in ("csv", "xlsx", "pdf"):
            log("report.exported", request=request, target=d["type"], detail=f"{report['subtitle']}; format={fmt}; rows={len(report['rows'])}")
            if fmt == "csv":
                return exports.to_csv(report)
            if fmt == "xlsx":
                return exports.to_xlsx(report, request.user.display_name)
            return exports.to_pdf(report, request.user.display_name)
    truncated = bool(report and len(report["rows"]) > MAX_PREVIEW_ROWS)
    qs = request.GET.copy()
    qs.pop("format", None)
    return render(request, "reports/index.html", {
        "form": form, "report": report, "rows": report["rows"][:MAX_PREVIEW_ROWS] if report else [],
        "truncated": truncated, "qs": qs.urlencode(),
    })
