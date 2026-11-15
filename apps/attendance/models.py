from django.conf import settings
from django.db import models


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "On time"
    LATE = "late", "Late"
    ABSENT = "absent", "Absent"
    ON_LEAVE = "on_leave", "On leave"


class AttendanceRecord(models.Model):
    """One row per employee per day."""

    employee = models.ForeignKey("employees.EmployeeProfile", on_delete=models.CASCADE, related_name="attendance_records")
    date = models.DateField(db_index=True)
    branch = models.ForeignKey("branches.Branch", null=True, blank=True, on_delete=models.SET_NULL, related_name="attendance_records")
    shift_name = models.CharField(max_length=80, blank=True)
    clock_in = models.DateTimeField(null=True, blank=True)
    clock_out = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=AttendanceStatus.choices, default=AttendanceStatus.PRESENT, db_index=True)
    late_minutes = models.PositiveIntegerField(default=0)
    early_departure_minutes = models.PositiveIntegerField(default=0)
    break_minutes = models.PositiveIntegerField(default=0)
    worked_minutes = models.PositiveIntegerField(default=0)
    overtime_minutes = models.PositiveIntegerField(default=0)
    in_distance_m = models.FloatField(null=True, blank=True)
    out_distance_m = models.FloatField(null=True, blank=True)
    corrected = models.BooleanField(default=False)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-date", "-clock_in"]
        constraints = [models.UniqueConstraint(fields=["employee", "date"], name="uniq_attendance_employee_date")]
        indexes = [
            models.Index(fields=["employee", "date"]),
            models.Index(fields=["branch", "date"]),
            models.Index(fields=["date", "status"]),
        ]

    def __str__(self):
        return f"{self.employee.employee_number} {self.date} {self.status}"

    @property
    def is_clocked_in(self):
        return bool(self.clock_in and not self.clock_out)

    @property
    def worked_display(self):
        return minutes_display(self.worked_minutes)

    @property
    def overtime_display(self):
        return minutes_display(self.overtime_minutes)


def minutes_display(total):
    h, m = divmod(int(total or 0), 60)
    return f"{h} h {m:02d} m"


class AttendanceEvent(models.Model):
    """Audit trail of every clock attempt, successful or not (incl. GPS data)."""

    class Type(models.TextChoices):
        CLOCK_IN = "clock_in", "Clock in"
        CLOCK_OUT = "clock_out", "Clock out"

    employee = models.ForeignKey("employees.EmployeeProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="attendance_events")
    record = models.ForeignKey(AttendanceRecord, null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    branch = models.ForeignKey("branches.Branch", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    event_type = models.CharField(max_length=10, choices=Type.choices)
    success = models.BooleanField(default=False, db_index=True)
    reason_code = models.CharField(max_length=40, blank=True)
    message = models.CharField(max_length=255, blank=True)
    suspicious = models.BooleanField(default=False, db_index=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    accuracy_m = models.FloatField(null=True, blank=True)
    branch_latitude = models.FloatField(null=True, blank=True)
    branch_longitude = models.FloatField(null=True, blank=True)
    distance_m = models.FloatField(null=True, blank=True)
    gps_result = models.CharField(max_length=40, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} {'OK' if self.success else 'REJECTED'} {self.created_at:%Y-%m-%d %H:%M}"


class CorrectionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class AttendanceCorrection(models.Model):
    employee = models.ForeignKey("employees.EmployeeProfile", on_delete=models.CASCADE, related_name="corrections")
    date = models.DateField()
    requested_clock_in = models.TimeField(null=True, blank=True)
    requested_clock_out = models.TimeField(null=True, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=10, choices=CorrectionStatus.choices, default=CorrectionStatus.PENDING, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Correction {self.employee.employee_number} {self.date}"
