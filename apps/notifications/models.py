from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Category(models.TextChoices):
        CLOCK = "clock", "Attendance"
        LATE = "late", "Late arrival"
        LEAVE = "leave", "Leave"
        CORRECTION = "correction", "Correction"
        ANNOUNCEMENT = "announcement", "Announcement"
        SYSTEM = "system", "System"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=120)
    message = models.CharField(max_length=400, blank=True)
    category = models.CharField(max_length=14, choices=Category.choices, default=Category.SYSTEM)
    link = models.CharField(max_length=200, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_read"])]

    def __str__(self):
        return f"{self.user}: {self.title}"
