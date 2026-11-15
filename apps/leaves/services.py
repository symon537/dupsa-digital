from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.services import log
from apps.core.models import CompanySettings, Holiday
from apps.notifications import services as notifications
from apps.notifications.models import Notification

from .models import LeaveApplication, LeaveBalance, LeaveStatus, LeaveType


class LeaveError(Exception):
    pass


def count_leave_days(start, end, profile=None):
    """Working days between two dates (inclusive), skipping non-working days and holidays."""
    working = set(CompanySettings.get().working_day_list)
    holidays = set(Holiday.objects.filter(date__range=(start, end)).values_list("date", flat=True))
    n, d = 0, start
    while d <= end:
        if d.weekday() in working and d not in holidays:
            n += 1
        d += timedelta(days=1)
    return Decimal(n)


def get_balance(profile, leave_type, year):
    bal, _ = LeaveBalance.objects.get_or_create(
        employee=profile, leave_type=leave_type, year=year,
        defaults={"entitled_days": Decimal(leave_type.days_per_year)},
    )
    return bal


def balances_for(profile, year):
    return [get_balance(profile, lt, year) for lt in LeaveType.objects.filter(is_active=True)]


def validate_application(profile, leave_type, start, end, has_document):
    if end < start:
        raise LeaveError("The end date cannot be before the start date.")
    if leave_type.gender_restriction and profile.gender != leave_type.gender_restriction:
        raise LeaveError(f"{leave_type.name} is not available for this employee.")
    if leave_type.requires_document and not has_document:
        raise LeaveError(f"{leave_type.name} requires a supporting document.")
    if start.year != end.year:
        raise LeaveError("Please submit separate applications for each calendar year.")
    overlap = LeaveApplication.objects.filter(
        employee=profile, status__in=[LeaveStatus.PENDING, LeaveStatus.APPROVED], start_date__lte=end, end_date__gte=start
    ).exists()
    if overlap:
        raise LeaveError("You already have a pending or approved leave overlapping these dates.")
    days = count_leave_days(start, end, profile)
    if days <= 0:
        raise LeaveError("The selected dates contain no working days.")
    if not leave_type.unlimited:
        bal = get_balance(profile, leave_type, start.year)
        pending = sum(
            (a.days for a in LeaveApplication.objects.filter(
                employee=profile, leave_type=leave_type, status=LeaveStatus.PENDING, start_date__year=start.year)),
            Decimal("0"),
        )
        if days > bal.remaining - pending:
            raise LeaveError(f"Not enough {leave_type.name} balance. Remaining: {bal.remaining - pending} day(s), requested: {days}.")
    return days


@transaction.atomic
def submit_application(profile, leave_type, start, end, reason="", document=None):
    days = validate_application(profile, leave_type, start, end, bool(document))
    app = LeaveApplication.objects.create(
        employee=profile, leave_type=leave_type, start_date=start, end_date=end, days=days, reason=reason, document=document
    )
    log("leave.applied", user=profile.user, target=profile.employee_number, detail=f"{leave_type.name} {start}..{end} ({days} d)")
    recipients = notifications.managers_of(profile) + list(notifications.hr_users())
    notifications.notify_many(recipients, f"Leave request: {profile.full_name}",
                              f"{leave_type.name}, {start:%d %b} - {end:%d %b} ({days} day(s)).",
                              Notification.Category.LEAVE, "/leaves/")
    notifications.notify(profile.user, "Leave request submitted", f"{leave_type.name}, {start:%d %b} - {end:%d %b}.",
                         Notification.Category.LEAVE, "/my/requests/")
    return app


@transaction.atomic
def review_application(app, reviewer, approve, note=""):
    app = LeaveApplication.objects.select_for_update().select_related("employee__user", "leave_type").get(pk=app.pk)
    if app.status != LeaveStatus.PENDING:
        raise LeaveError("This application has already been reviewed.")
    if approve and not app.leave_type.unlimited:
        bal = get_balance(app.employee, app.leave_type, app.start_date.year)
        if app.days > bal.remaining:
            raise LeaveError(f"Insufficient balance ({bal.remaining} day(s) left).")
        bal.used_days += app.days
        bal.save()
    app.status = LeaveStatus.APPROVED if approve else LeaveStatus.REJECTED
    app.reviewed_by, app.reviewed_at, app.review_note = reviewer, timezone.now(), note[:255]
    app.save()
    if approve and app.leave_type.unlimited:
        pass  # no balance to deduct
    verb = "approved" if approve else "rejected"
    log(f"leave.{verb}", user=reviewer, target=app.employee.employee_number,
        detail=f"{app.leave_type.name} {app.start_date}..{app.end_date}; note={note}")
    notifications.notify(app.employee.user, f"Leave {verb}",
                         f"Your {app.leave_type.name} ({app.start_date:%d %b} - {app.end_date:%d %b}) was {verb}."
                         + (f" Note: {note}" if note else ""), Notification.Category.LEAVE, "/my/requests/")
    return app


@transaction.atomic
def cancel_application(app):
    app = LeaveApplication.objects.select_for_update().get(pk=app.pk)
    if app.status not in (LeaveStatus.PENDING, LeaveStatus.APPROVED):
        raise LeaveError("This application cannot be cancelled.")
    if app.status == LeaveStatus.APPROVED and not app.leave_type.unlimited:
        bal = get_balance(app.employee, app.leave_type, app.start_date.year)
        bal.used_days = max(Decimal("0"), bal.used_days - app.days)
        bal.save()
    app.status = LeaveStatus.CANCELLED
    app.save()
    return app
