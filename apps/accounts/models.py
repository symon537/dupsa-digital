from django.contrib.auth.models import AbstractUser
from django.db import models


class Role(models.TextChoices):
    SUPER_ADMIN = "super_admin", "Super Administrator"
    DIRECTOR = "director", "Director / Managing Director"
    HR_MANAGER = "hr_manager", "HR Manager"
    BRANCH_MANAGER = "branch_manager", "Branch Manager"
    SUPERVISOR = "supervisor", "Supervisor"
    EMPLOYEE = "employee", "Employee"


class User(AbstractUser):
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.EMPLOYEE, db_index=True)
    phone = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def save(self, *args, **kwargs):
        # createsuperuser must always yield a Super Administrator.
        if self.is_superuser:
            self.role = Role.SUPER_ADMIN
        super().save(*args, **kwargs)

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def role_label(self):
        return self.get_role_display()

    @property
    def is_super_admin(self):
        return self.role == Role.SUPER_ADMIN

    @property
    def is_staff_role(self):
        return self.role != Role.EMPLOYEE

    @property
    def has_profile(self):
        return hasattr(self, "employee_profile")

    def __str__(self):
        return self.display_name
