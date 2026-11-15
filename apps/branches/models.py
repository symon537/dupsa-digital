from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

QR_SALT = "malkia.branch.qr"


class Branch(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)
    address = models.CharField(max_length=255, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.DecimalField(max_digits=9, decimal_places=6, validators=[MinValueValidator(-180), MaxValueValidator(180)])
    radius_m = models.PositiveIntegerField(
        "attendance radius (m)", default=100, validators=[MinValueValidator(10), MaxValueValidator(5000)]
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="managed_branches"
    )
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "branches"

    def __str__(self):
        return self.name

    @property
    def active_qr(self):
        return self.qr_codes.filter(is_active=True).order_by("-issued_at").first()

    def ensure_qr(self):
        return self.active_qr or OfficeQRCode.issue(self)


class OfficeQRCode(models.Model):
    """A signed, expiring QR token that identifies a *branch* (never an employee)."""

    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name="qr_codes")
    token = models.CharField(max_length=255, unique=True)
    issued_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True, db_index=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-issued_at"]
        indexes = [models.Index(fields=["branch", "is_active"])]

    def __str__(self):
        return f"QR {self.branch.code} ({'active' if self.is_active else 'revoked'})"

    @property
    def is_expired(self):
        return self.expires_at <= timezone.now()

    @classmethod
    def issue(cls, branch, user=None, validity_days=None):
        """Create a new token and revoke every earlier one (rotation)."""
        import secrets

        from apps.core.models import CompanySettings

        days = validity_days or CompanySettings.get().qr_validity_days
        now = timezone.now()
        token = signing.dumps({"b": branch.pk, "n": secrets.token_hex(6)}, salt=QR_SALT, compress=True)
        cls.objects.filter(branch=branch, is_active=True).update(is_active=False)
        return cls.objects.create(
            branch=branch, token=token, issued_at=now, expires_at=now + timedelta(days=days), issued_by=user
        )

    @property
    def scan_url(self):
        from urllib.parse import quote

        return f"{settings.SITE_URL}/my/scan/?t={quote(self.token, safe='')}"
