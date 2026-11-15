from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import VIEW_STAFF

from . import analytics
from .models import AttendanceRecord
from .services import CLOCK_IN, CLOCK_OUT, AttendanceError, process_clock, validate_qr_token


class ClockSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=500, trim_whitespace=True)
    latitude = serializers.FloatField(required=False, allow_null=True, min_value=-90, max_value=90)
    longitude = serializers.FloatField(required=False, allow_null=True, min_value=-180, max_value=180)
    accuracy = serializers.FloatField(required=False, allow_null=True, min_value=0)


def record_payload(record):
    if record is None:
        return None
    ci = timezone.localtime(record.clock_in) if record.clock_in else None
    co = timezone.localtime(record.clock_out) if record.clock_out else None
    return {
        "date": record.date.isoformat(),
        "clock_in": ci.strftime("%H:%M") if ci else None,
        "clock_out": co.strftime("%H:%M") if co else None,
        "worked": record.worked_display if record.clock_out else None,
        "worked_minutes": record.worked_minutes,
        "status": record.status,
        "status_label": record.get_status_display(),
        "late_minutes": record.late_minutes,
        "overtime_minutes": record.overtime_minutes,
        "branch": record.branch.name if record.branch else None,
    }


def _meta(request):
    from apps.accounts.security import client_ip

    return {"ip": client_ip(request), "user_agent": request.META.get("HTTP_USER_AGENT", "")}


class ClockView(APIView):
    action = None
    throttle_scope = "attendance"

    def post(self, request):
        ser = ClockSerializer(data=request.data)
        if not ser.is_valid():
            return Response({"ok": False, "code": "invalid_input", "message": "Invalid attendance data.", "errors": ser.errors},
                            status=status.HTTP_400_BAD_REQUEST)
        d = ser.validated_data
        try:
            result = process_clock(
                request.user, self.action, d["token"], d.get("latitude"), d.get("longitude"), d.get("accuracy"),
                meta=_meta(request),
            )
        except AttendanceError as exc:
            code = status.HTTP_403_FORBIDDEN if exc.code in ("branch_not_allowed", "inactive", "no_profile") else status.HTTP_400_BAD_REQUEST
            return Response({"ok": False, "code": exc.code, "message": exc.message,
                             "distance_m": exc.gps.distance_m if exc.gps else None}, status=code)
        verb = "Clocked in" if self.action == CLOCK_IN else "Clocked out"
        return Response({
            "ok": True,
            "message": f"{verb} at {result['branch'].name}. {result['gps'].message}",
            "gps": {"code": result["gps"].code, "distance_m": result["gps"].distance_m},
            "record": record_payload(result["record"]),
        })


class ClockInView(ClockView):
    action = CLOCK_IN


class ClockOutView(ClockView):
    action = CLOCK_OUT


class QRCheckView(APIView):
    """Lets the scan page show which branch a QR code belongs to before the employee confirms."""

    throttle_scope = "attendance"

    def post(self, request):
        try:
            qr = validate_qr_token(request.data.get("token", ""))
        except AttendanceError as exc:
            return Response({"ok": False, "code": exc.code, "message": exc.message}, status=status.HTTP_400_BAD_REQUEST)
        profile = getattr(request.user, "employee_profile", None)
        allowed = bool(profile and profile.can_clock_at(qr.branch))
        return Response({"ok": True, "branch": qr.branch.name, "branch_code": qr.branch.code, "allowed": allowed,
                         "radius_m": qr.branch.radius_m})


class TodayView(APIView):
    throttle_scope = "attendance"

    def get(self, request):
        profile = getattr(request.user, "employee_profile", None)
        if profile is None:
            return Response({"ok": False, "message": "No employee profile."}, status=status.HTTP_404_NOT_FOUND)
        record = AttendanceRecord.objects.filter(employee=profile, date=timezone.localdate()).select_related("branch").first()
        return Response({"ok": True, "record": record_payload(record), "clocked_in": bool(record and record.is_clocked_in)})


class DashboardChartsView(APIView):
    throttle_scope = "dashboard"

    def get(self, request):
        if request.user.role not in VIEW_STAFF:
            return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)
        return Response({"stats": _jsonable(analytics.dashboard_stats(request.user)), "charts": analytics.chart_data(request.user)})


def _jsonable(d):
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.items()}
