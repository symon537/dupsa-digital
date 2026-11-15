from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

WEEKDAY_CHOICES = [
    (0, "Monday"), (1, "Tuesday"), (2, "Wednesday"), (3, "Thursday"),
    (4, "Friday"), (5, "Saturday"), (6, "Sunday"),
]


def parse_days(value):
    """'0,1,2' -> [0, 1, 2]"""
    return [int(x) for x in str(value or "").split(",") if x.strip().isdigit()]


class CompanySettings(models.Model):
    """Single-row table with company-wide attendance policy and branding."""

    company_name = models.CharField(max_length=120, default="Malkia Konnect")
    enforce_gps = models.BooleanField(
        default=True, help_text="Reject clock-in/out when the employee is outside the branch radius."
    )
    max_gps_accuracy_m = models.PositiveIntegerField(
        default=100,
        validators=[MinValueValidator(5), MaxValueValidator(5000)],
        help_text="Reject GPS readings less accurate than this (metres).",
    )
    working_days = models.CharField(
        max_length=20, default="0,1,2,3,4,5", help_text="Default working days (0=Monday ... 6=Sunday)."
    )
    overtime_threshold_minutes = models.PositiveIntegerField(
        default=15, help_text="Minutes after shift end before time counts as overtime."
    )
    qr_validity_days = models.PositiveIntegerField(
        default=90, validators=[MinValueValidator(1), MaxValueValidator(3650)],
        help_text="How long a newly issued branch QR code stays valid.",
    )
    login_background = models.ImageField(upload_to="branding/", blank=True, null=True)
    login_background_enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "company settings"

    def __str__(self):
        return self.company_name

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    @property
    def working_day_list(self):
        return parse_days(self.working_days)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)


class Holiday(models.Model):
    date = models.DateField()
    name = models.CharField(max_length=120)
    branch = models.ForeignKey(
        "branches.Branch", null=True, blank=True, on_delete=models.CASCADE,
        help_text="Leave empty for a company-wide holiday.",
    )

    class Meta:
        ordering = ["date"]
        constraints = [models.UniqueConstraint(fields=["date", "branch"], name="uniq_holiday_date_branch")]

    def __str__(self):
        return f"{self.name} ({self.date})"
