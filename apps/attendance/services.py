"""Server-side attendance rules: QR validation, GPS verification, clock in/out, calculations.

Everything the employee's phone sends is treated as untrusted input and validated here.
"""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services import log as audit_log
from apps.branches.models import QR_SALT, OfficeQRCode
from apps.core.models import CompanySettings, Holiday
from apps.notifications import services as notifications
from apps.notifications.models import Notification
from apps.shifts.models import get_shift_for

from .models import AttendanceEvent, AttendanceRecord, AttendanceStatus

CLOCK_IN = "clock_in"
CLOCK_OUT = "clock_out"
MIN_MINUTES_FOR_BREAK = 240  # the shift break is only deducted after 4 hours on site


class AttendanceError(Exception):
    """A rejected attendance attempt. ``code`` is machine-readable, ``message`` is shown to the employee."""

    def __init__(self, code, message, suspicious=False, branch=None, gps=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.suspicious = suspicious
        self.branch = branch
        self.gps = gps


@dataclass
class GPSResult:
    ok: bool
    code: str
    message: str
    distance_m: float = None


# ------------------------------------------------------------------ helpers
def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def is_working_day(profile, day, shift=None):
    if Holiday.objects.filter(date=day).filter(branch__isnull=True).exists():
        return False
    if Holiday.objects.filter(date=day, branch=profile.branch).exists():
        return False
    shift = shift or get_shift_for(profile, day)
    return shift.is_working_day(day)


def _aware(day, t):
    return timezone.make_aware(datetime.combine(day, t), timezone.get_current_timezone())


# ---------------------------------------------------------------------- QR
def validate_qr_token(token):
    """Return the active OfficeQRCode for a token or raise AttendanceError."""
    token = (token or "").strip()
    if not token:
        raise AttendanceError("qr_missing", "Please scan the Malkia Konnect office QR code.")
    try:
        signing.loads(token, salt=QR_SALT)
    except signing.BadSignature:
        raise AttendanceError("qr_invalid", "This QR code is not valid. Please scan the official office QR code.", suspicious=True)
    qr = OfficeQRCode.objects.select_related("branch").filter(token=token).first()
    if qr is None:
        raise AttendanceError("qr_unknown", "This QR code is not recognised.", suspicious=True)
    if not qr.is_active:
        raise AttendanceError("qr_revoked", "This QR code has been replaced. Please scan the current office QR code.", branch=qr.branch)
    if qr.is_expired:
        raise AttendanceError("qr_expired", "This QR code has expired. Please ask HR for the new office QR code.", branch=qr.branch)
    if not qr.branch.is_active:
        raise AttendanceError("branch_inactive", "This branch is not active.", branch=qr.branch)
    return qr


# --------------------------------------------------------------------- GPS
def verify_gps(branch, lat, lon, accuracy, company=None):
    company = company or CompanySettings.get()
    if lat is None or lon is None:
        if company.enforce_gps:
            return GPSResult(False, "permission_required", "Location permission required. Please allow location access and try again.")
        return GPSResult(True, "not_enforced", "Location not provided (GPS enforcement is off).")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return GPSResult(False, "invalid_coordinates", "Invalid location received.")
    distance = haversine_m(lat, lon, float(branch.latitude), float(branch.longitude))
    if company.enforce_gps:
        if accuracy is None or accuracy > company.max_gps_accuracy_m:
            return GPSResult(False, "low_accuracy", "GPS accuracy is insufficient. Move to an open area and try again.", distance)
        if distance > branch.radius_m:
            return GPSResult(False, "outside_radius", "You are outside the allowed attendance area.", distance)
        return GPSResult(True, "verified", "Location verified. You are within the office area.", distance)
    return GPSResult(True, "not_enforced", "Location recorded (GPS enforcement is off).", distance)


# ------------------------------------------------------- calculations
def calculate_clock_in(shift, clock_in_dt):
    """Return (status, late_minutes) for a clock-in time."""
    local = timezone.localtime(clock_in_dt)
    start = _aware(local.date(), shift.start_time)
    grace_limit = start + timedelta(minutes=shift.grace_minutes)
    if local > grace_limit:
        return AttendanceStatus.LATE, int((local - start).total_seconds() // 60)
    return AttendanceStatus.PRESENT, 0


def calculate_clock_out(shift, clock_in_dt, clock_out_dt, working_day=True, overtime_threshold=15):
    """Return dict(worked, break_minutes, early, overtime) in minutes."""
    local_out = timezone.localtime(clock_out_dt)
    total = max(0, int((clock_out_dt - clock_in_dt).total_seconds() // 60))
    brk = shift.break_minutes if total >= MIN_MINUTES_FOR_BREAK else 0
    brk = min(brk, total)
    worked = total - brk
    end = _aware(local_out.date(), shift.end_time)
    early = int((end - local_out).total_seconds() // 60) if local_out < end else 0
    overtime = 0
    if not working_day:
        overtime = worked
    elif local_out > end + timedelta(minutes=overtime_threshold):
        overtime = int((local_out - end).total_seconds() // 60)
    return {"worked": worked, "break_minutes": brk, "early": early, "overtime": overtime}


# --------------------------------------------------------------- main API
def _has_approved_leave(profile, day):
    from apps.leaves.models import LeaveApplication, LeaveStatus

    return LeaveApplication.objects.filter(
        employee=profile, status=LeaveStatus.APPROVED, start_date__lte=day, end_date__gte=day
    ).exists()


def _record_event(profile, action, success, branch=None, code="", message="", suspicious=False, gps=None,
                  lat=None, lon=None, accuracy=None, meta=None, record=None):
    meta = meta or {}
    return AttendanceEvent.objects.create(
        employee=profile,
        record=record,
        branch=branch,
        event_type=action,
        success=success,
        reason_code=code[:40],
        message=message[:255],
        suspicious=suspicious,
        latitude=lat,
        longitude=lon,
        accuracy_m=accuracy,
        branch_latitude=float(branch.latitude) if branch else None,
        branch_longitude=float(branch.longitude) if branch else None,
        distance_m=gps.distance_m if gps else None,
        gps_result=gps.code if gps else "",
        ip_address=meta.get("ip") or None,
        user_agent=(meta.get("user_agent") or "")[:255],
    )


def process_clock(user, action, token, lat=None, lon=None, accuracy=None, meta=None, now=None):
    """Validate and record a clock-in or clock-out. Returns a result dict or raises AttendanceError."""
    now = now or timezone.now()
    profile = getattr(user, "employee_profile", None)
    if profile is None:
        raise AttendanceError("no_profile", "Your account is not linked to an employee profile.")
    try:
        result = _process(profile, action, token, lat, lon, accuracy, meta or {}, now)
    except AttendanceError as exc:
        _record_event(profile, action, False, branch=exc.branch, code=exc.code, message=exc.message,
                      suspicious=exc.suspicious, gps=exc.gps, lat=lat, lon=lon, accuracy=accuracy, meta=meta)
        audit_log("attendance.rejected", user=user, target=profile.employee_number,
                  detail=f"{action} rejected: {exc.code} - {exc.message}", ip=(meta or {}).get("ip"))
        raise
    return result


def _process(profile, action, token, lat, lon, accuracy, meta, now):
    if action not in (CLOCK_IN, CLOCK_OUT):
        raise AttendanceError("bad_action", "Unknown attendance action.")
    if not profile.is_active_employee:
        raise AttendanceError("inactive", "Your employee account is not active. Please contact HR.")

    qr = validate_qr_token(token)
    branch = qr.branch
    if not profile.can_clock_at(branch):
        raise AttendanceError(
            "branch_not_allowed",
            f"You are not authorised to clock in at {branch.name}. Please use your own branch or ask HR.",
            suspicious=True, branch=branch,
        )

    company = CompanySettings.get()
    gps = verify_gps(branch, lat, lon, accuracy, company)
    if not gps.ok:
        raise AttendanceError(gps.code, gps.message, suspicious=gps.code in ("outside_radius", "invalid_coordinates"),
                              branch=branch, gps=gps)

    today = timezone.localtime(now).date()
    shift = get_shift_for(profile, today)

    if action == CLOCK_IN:
        record = _clock_in(profile, branch, shift, gps, today, now)
    else:
        record = _clock_out(profile, branch, shift, gps, today, now, company)

    event = _record_event(profile, action, True, branch=branch, code=gps.code, message=gps.message, gps=gps,
                          lat=lat, lon=lon, accuracy=accuracy, meta=meta, record=record)
    audit_log(f"attendance.{action}", user=profile.user, target=profile.employee_number,
              detail=f"{branch.name}; distance={gps.distance_m and round(gps.distance_m)} m; gps={gps.code}", ip=meta.get("ip"))
    _notify(profile, action, record, branch, now)
    return {"record": record, "event": event, "gps": gps, "branch": branch}


def _clock_in(profile, branch, shift, gps, today, now):
    if _has_approved_leave(profile, today):
        raise AttendanceError("on_leave", "You are on approved leave today. Please contact HR if this is wrong.", branch=branch)
    try:
        with transaction.atomic():
            record, created = AttendanceRecord.objects.select_for_update().get_or_create(
                employee=profile, date=today, defaults={"branch": branch}
            )
            if record.clock_in is not None:
                raise AttendanceError("duplicate_clock_in", "You have already clocked in today.", branch=branch)
            status, late = calculate_clock_in(shift, now)
            record.branch = branch
            record.shift_name = getattr(shift, "name", "")
            record.clock_in = now
            record.status = status
            record.late_minutes = late
            record.in_distance_m = gps.distance_m
            record.save()
    except IntegrityError:  # two simultaneous requests: the unique constraint wins
        raise AttendanceError("duplicate_clock_in", "You have already clocked in today.", branch=branch)
    return record


def _clock_out(profile, branch, shift, gps, today, now, company):
    with transaction.atomic():
        record = AttendanceRecord.objects.select_for_update().filter(employee=profile, date=today).first()
        if record is None or record.clock_in is None:
            raise AttendanceError("no_active_clock_in", "You have not clocked in today, so you cannot clock out.", branch=branch)
        if record.clock_out is not None:
            raise AttendanceError("duplicate_clock_out", "You have already clocked out today.", branch=branch)
        if now <= record.clock_in:
            raise AttendanceError("bad_time", "Clock-out time must be after clock-in time.", branch=branch)
        calc = calculate_clock_out(
            shift, record.clock_in, now,
            working_day=is_working_day(profile, today, shift),
            overtime_threshold=company.overtime_threshold_minutes,
        )
        record.clock_out = now
        record.worked_minutes = calc["worked"]
        record.break_minutes = calc["break_minutes"]
        record.early_departure_minutes = calc["early"]
        record.overtime_minutes = calc["overtime"]
        record.out_distance_m = gps.distance_m
        record.save()
    return record


def _notify(profile, action, record, branch, now):
    local = timezone.localtime(now)
    if action == CLOCK_IN:
        notifications.notify(profile.user, "Clock-in recorded", f"{branch.name} at {local:%H:%M}.",
                             Notification.Category.CLOCK, "/my/")
        if record.status == AttendanceStatus.LATE:
            notifications.notify_many(
                notifications.managers_of(profile), f"Late arrival: {profile.full_name}",
                f"{profile.employee_number} clocked in {record.late_minutes} min late at {branch.name} ({local:%H:%M}).",
                Notification.Category.LATE, "/attendance/",
            )
            notifications.notify(profile.user, "You arrived late",
                                 f"You clocked in {record.late_minutes} minutes after shift start.", Notification.Category.LATE, "/my/")
    else:
        notifications.notify(profile.user, "Clock-out recorded",
                             f"{branch.name} at {local:%H:%M}. Worked {record.worked_display}.", Notification.Category.CLOCK, "/my/")


def apply_correction(correction, reviewer, approve, note=""):
    """Approve or reject an attendance correction request; approval rewrites the day's record."""
    from .models import CorrectionStatus

    if correction.status != CorrectionStatus.PENDING:
        raise ValueError("This correction has already been reviewed.")
    correction.reviewed_by = reviewer
    correction.reviewed_at = timezone.now()
    correction.review_note = note[:255]
    if not approve:
        correction.status = CorrectionStatus.REJECTED
        correction.save()
        return None
    profile = correction.employee
    with transaction.atomic():
        record, _ = AttendanceRecord.objects.select_for_update().get_or_create(
            employee=profile, date=correction.date, defaults={"branch": profile.branch}
        )
        shift = get_shift_for(profile, correction.date)
        if correction.requested_clock_in:
            record.clock_in = _aware(correction.date, correction.requested_clock_in)
            status, late = calculate_clock_in(shift, record.clock_in)
            record.status, record.late_minutes = status, late
        if correction.requested_clock_out and record.clock_in:
            out = _aware(correction.date, correction.requested_clock_out)
            if out > record.clock_in:
                record.clock_out = out
                calc = calculate_clock_out(shift, record.clock_in, out, is_working_day(profile, correction.date, shift),
                                           CompanySettings.get().overtime_threshold_minutes)
                record.worked_minutes, record.break_minutes = calc["worked"], calc["break_minutes"]
                record.early_departure_minutes, record.overtime_minutes = calc["early"], calc["overtime"]
        record.shift_name = getattr(shift, "name", "")
        record.corrected = True
        record.notes = f"Corrected by {reviewer.display_name}"[:255]
        record.save()
        correction.status = CorrectionStatus.APPROVED
        correction.save()
    return record
