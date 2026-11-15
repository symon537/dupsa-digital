from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models, transaction

phone_validator = RegexValidator(r"^\+?[0-9 ()-]{7,20}$", "Enter a valid phone number, e.g. +255 712 345 678.")


class EmploymentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    PROBATION = "probation", "On probation"
    SUSPENDED = "suspended", "Suspended"
    TERMINATED = "terminated", "Terminated"
    RESIGNED = "resigned", "Resigned"


class Gender(models.TextChoices):
    FEMALE = "F", "Female"
    MALE = "M", "Male"
    OTHER = "O", "Other"


ACTIVE_STATUSES = (EmploymentStatus.ACTIVE, EmploymentStatus.PROBATION)


class EmployeeProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="employee_profile")
    employee_number = models.CharField(max_length=20, unique=True, blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices, default=Gender.FEMALE)
    phone = models.CharField(max_length=20, blank=True, validators=[phone_validator])
    address = models.CharField(max_length=255, blank=True)
    photo = models.ImageField(upload_to="employees/", blank=True, null=True)
    department = models.ForeignKey("departments.Department", null=True, blank=True, on_delete=models.SET_NULL, related_name="employees")
    position = models.ForeignKey("departments.Position", null=True, blank=True, on_delete=models.SET_NULL, related_name="employees")
    branch = models.ForeignKey("branches.Branch", on_delete=models.PROTECT, related_name="employees")
    allowed_branches = models.ManyToManyField(
        "branches.Branch", blank=True, related_name="visiting_employees",
        help_text="Other branches where this employee may also clock in.",
    )
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="supervised_employees"
    )
    employment_date = models.DateField()
    status = models.CharField(max_length=12, choices=EmploymentStatus.choices, default=EmploymentStatus.ACTIVE, db_index=True)
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(max_length=20, blank=True, validators=[phone_validator])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee_number"]
        indexes = [models.Index(fields=["branch", "status"]), models.Index(fields=["department", "status"])]

    def __str__(self):
        return f"{self.full_name} ({self.employee_number})"

    @property
    def full_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def is_active_employee(self):
        return self.status in ACTIVE_STATUSES and self.user.is_active

    @property
    def initials(self):
        parts = self.full_name.split()
        return "".join(p[0] for p in parts[:2]).upper()

    def can_clock_at(self, branch):
        if branch.pk == self.branch_id:
            return True
        return self.allowed_branches.filter(pk=branch.pk).exists()

    def save(self, *args, **kwargs):
        if not self.employee_number:
            with transaction.atomic():
                last = EmployeeProfile.objects.order_by("-id").values_list("id", flat=True).first() or 0
                n = last + 1
                while EmployeeProfile.objects.filter(employee_number=f"MK-{n:04d}").exists():
                    n += 1
                self.employee_number = f"MK-{n:04d}"
        super().save(*args, **kwargs)
