from datetime import timedelta

from django import forms
from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.permissions import MANAGE_ORG, VIEW_STAFF, role_required
from apps.audit.services import log
from apps.core.forms import BootstrapForm, BootstrapModelForm, DateInput, TimeInput
from apps.core.models import WEEKDAY_CHOICES, parse_days
from apps.employees.models import ACTIVE_STATUSES, EmployeeProfile

from .models import ShiftAssignment, WorkShift


class ShiftForm(BootstrapModelForm):
    days = forms.MultipleChoiceField(choices=WEEKDAY_CHOICES, widget=forms.CheckboxSelectMultiple, label="Working days")

    class Meta:
        model = WorkShift
        fields = ["name", "start_time", "end_time", "break_minutes", "grace_minutes", "days", "branch", "department", "is_active"]
        widgets = {"start_time": TimeInput(), "end_time": TimeInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["days"].initial = [str(d) for d in parse_days(self.instance.working_days)] or ["0", "1", "2", "3", "4", "5"]

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.working_days = ",".join(sorted(self.cleaned_data["days"]))
        if commit:
            obj.save()
        return obj


class AssignForm(BootstrapForm):
    shift = forms.ModelChoiceField(queryset=WorkShift.objects.filter(is_active=True))
    employees = forms.ModelMultipleChoiceField(queryset=EmployeeProfile.objects.none(), widget=forms.SelectMultiple(attrs={"size": 10}))
    start_date = forms.DateField(widget=DateInput(), initial=timezone.localdate)
    end_date = forms.DateField(widget=DateInput(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employees"].queryset = EmployeeProfile.objects.filter(status__in=ACTIVE_STATUSES).select_related("user", "branch")
        self.fields["employees"].label_from_instance = lambda e: f"{e.employee_number} - {e.full_name} ({e.branch.name})"

    def clean(self):
        data = super().clean()
        if data.get("end_date") and data.get("start_date") and data["end_date"] < data["start_date"]:
            self.add_error("end_date", "End date cannot be before the start date.")
        return data


@role_required(*VIEW_STAFF)
def shift_list(request):
    shifts = WorkShift.objects.select_related("branch", "department").annotate(n=Count("assignments"))
    assignments = ShiftAssignment.objects.select_related("employee__user", "shift")[:50]
    return render(request, "shifts/list.html", {"shifts": shifts, "assignments": assignments, "can_manage": request.user.role in MANAGE_ORG})


@role_required(*MANAGE_ORG)
def shift_edit(request, pk=None):
    shift = get_object_or_404(WorkShift, pk=pk) if pk else None
    form = ShiftForm(request.POST or None, instance=shift)
    if request.method == "POST" and form.is_valid():
        s = form.save()
        log("shift.created" if pk is None else "shift.updated", request=request, target=s.name,
            detail=f"{s.start_time:%H:%M}-{s.end_time:%H:%M}; days={s.working_days}")
        messages.success(request, f"Shift '{s.name}' saved.")
        return redirect("shifts:list")
    return render(request, "generic_form.html", {"form": form, "title": f"Edit shift: {shift.name}" if shift else "Create shift", "back": "shifts:list"})


@role_required(*MANAGE_ORG)
def shift_assign(request):
    form = AssignForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        count = 0
        for emp in d["employees"]:
            # close any open assignment that would overlap the new one
            ShiftAssignment.objects.filter(employee=emp, end_date__isnull=True, start_date__lt=d["start_date"]).update(
                end_date=d["start_date"] - timedelta(days=1)
            )
            ShiftAssignment.objects.create(employee=emp, shift=d["shift"], start_date=d["start_date"], end_date=d.get("end_date"))
            count += 1
        log("shift.assigned", request=request, target=d["shift"].name, detail=f"{count} employee(s) from {d['start_date']}")
        messages.success(request, f"Shift '{d['shift'].name}' assigned to {count} employee(s).")
        return redirect("shifts:list")
    return render(request, "shifts/assign.html", {"form": form})


@role_required(*MANAGE_ORG)
@require_POST
def assignment_delete(request, pk):
    a = get_object_or_404(ShiftAssignment, pk=pk)
    log("shift.unassigned", request=request, target=a.shift.name, detail=a.employee.employee_number)
    a.delete()
    messages.success(request, "Assignment removed.")
    return redirect("shifts:list")
