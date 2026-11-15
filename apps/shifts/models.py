from dataclasses import dataclass
from datetime import time

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import CompanySettings, parse_days


class WorkShift(models.Model):
    name = models.CharField(max_length=80, unique=True)
    start_time = models.TimeField(default=time(8, 0))
    end_time = models.TimeField(default=time(17, 0))
    break_minutes = models.PositiveIntegerField(default=60)
    grace_minutes = models.PositiveIntegerField(default=15)
    working_days = models.CharField(max_length=20, default="0,1,2,3,4,5", help_text="0=Monday ... 6=Sunday, comma separated.")
    branch = models.ForeignKey("branches.Branch", null=True, blank=True, on_delete=models.CASCADE, related_name="shifts")
    department = models.ForeignKey("departments.Department", null=True, blank=True, on_delete=models.CASCADE, related_name="shifts")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["start_time", "name"]

    def __str__(self):
        return f"{self.name} ({self.start_time:%H:%M}-{self.end_time:%H:%M})"

    def clean(self):
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError("Shift end time must be after the start time (overnight shifts are not supported).")

    @property
    def working_day_list(self):
        return parse_days(self.working_days)

    def is_working_day(self, d):
        return d.weekday() in self.working_day_list

    @property
    def duration_minutes(self):
        return (self.end_time.hour * 60 + self.end_time.minute) - (self.start_time.hour * 60 + self.start_time.minute)


class ShiftAssignment(models.Model):
    employee = models.ForeignKey("employees.EmployeeProfile", on_delete=models.CASCADE, related_name="shift_assignments")
    shift = models.ForeignKey(WorkShift, on_delete=models.PROTECT, related_name="assignments")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-start_date"]
        indexes = [models.Index(fields=["employee", "start_date"])]

    def __str__(self):
        return f"{self.employee} -> {self.shift}"

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError("End date cannot be before the start date.")


@dataclass
class FallbackShift:
    """Used when HR has not configured any shift yet."""

    name: str = "Default (08:00-17:00)"
    start_time: time = time(8, 0)
    end_time: time = time(17, 0)
    break_minutes: int = 60
    grace_minutes: int = 15
    pk: int = None

    def is_working_day(self, d):
        return d.weekday() in CompanySettings.get().working_day_list


def get_shift_for(profile, on_date):
    """Resolve the shift that applies to an employee on a date.

    Order: explicit assignment > branch+department shift > branch shift > department shift > company default shift.
    """
    assignment = (
        ShiftAssignment.objects.filter(employee=profile, start_date__lte=on_date, shift__is_active=True)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=on_date))
        .select_related("shift")
        .order_by("-start_date")
        .first()
    )
    if assignment:
        return assignment.shift
    shifts = WorkShift.objects.filter(is_active=True)
    candidates = [
        shifts.filter(branch=profile.branch, department=profile.department) if profile.department_id else None,
        shifts.filter(branch=profile.branch, department__isnull=True),
        shifts.filter(branch__isnull=True, department=profile.department) if profile.department_id else None,
        shifts.filter(branch__isnull=True, department__isnull=True),
    ]
    for qs in candidates:
        if qs is not None:
            found = qs.order_by("id").first()
            if found:
                return found
    return FallbackShift()
