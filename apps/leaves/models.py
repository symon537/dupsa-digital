from decimal import Decimal

from django.conf import settings
from django.db import models


class LeaveType(models.Model):
    name = models.CharField(max_length=60, unique=True)
    days_per_year = models.PositiveIntegerField(default=0, help_text="0 = no fixed limit (e.g. unpaid leave).")
    is_paid = models.BooleanField(default=True)
    requires_document = models.BooleanField(default=False)
    gender_restriction = models.CharField(
        max_length=1, blank=True, choices=[("", "Any"), ("F", "Female only"), ("M", "Male only")]
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def unlimited(self):
        return self.days_per_year == 0


class LeaveStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"


class LeaveApplication(models.Model):
    employee = models.ForeignKey("employees.EmployeeProfile", on_delete=models.CASCADE, related_name="leave_applications")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT, related_name="applications")
    start_date = models.DateField()
    end_date = models.DateField()
    days = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal("0"))
    reason = models.TextField(blank=True)
    document = models.FileField(upload_to="leave_documents/", blank=True, null=True)
    status = models.CharField(max_length=10, choices=LeaveStatus.choices, default=LeaveStatus.PENDING, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["employee", "start_date", "end_date"]), models.Index(fields=["status", "start_date"])]

    def __str__(self):
        return f"{self.employee.employee_number} {self.leave_type} {self.start_date}..{self.end_date}"


class LeaveBalance(models.Model):
    employee = models.ForeignKey("employees.EmployeeProfile", on_delete=models.CASCADE, related_name="leave_balances")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, related_name="balances")
    year = models.PositiveIntegerField()
    entitled_days = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal("0"))
    used_days = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal("0"))

    class Meta:
        constraints = [models.UniqueConstraint(fields=["employee", "leave_type", "year"], name="uniq_leave_balance")]

    @property
    def remaining(self):
        return self.entitled_days - self.used_days

    def __str__(self):
        return f"{self.employee.employee_number} {self.leave_type} {self.year}"
