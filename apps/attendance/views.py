from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.permissions import APPROVE_CORRECTIONS, VIEW_ATTENDANCE, role_required, visible_employees
from apps.audit.services import log
from apps.branches.models import Branch
from apps.departments.models import Department
from apps.notifications import services as notifications
from apps.notifications.models import Notification

from .models import AttendanceCorrection, AttendanceRecord, AttendanceStatus, CorrectionStatus
from .services import apply_correction


def _parse_date(value, default):
    from datetime import date

    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return default


@role_required(*VIEW_ATTENDANCE)
def attendance_list(request):
    today = timezone.localdate()
    start = _parse_date(request.GET.get("from"), today)
    end = _parse_date(request.GET.get("to"), start)
    ids = visible_employees(request.user).values_list("pk", flat=True)
    qs = AttendanceRecord.objects.filter(employee_id__in=ids, date__range=(start, end)).select_related(
        "employee__user", "employee__department", "branch"
    )
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(employee__user__first_name__icontains=q) | Q(employee__user__last_name__icontains=q) | Q(employee__employee_number__icontains=q))
    for param, field in (("branch", "branch_id"), ("department", "employee__department_id"), ("status", "status")):
        if request.GET.get(param):
            qs = qs.filter(**{field: request.GET[param]})
    page = Paginator(qs.order_by("-date", "-clock_in"), 25).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "attendance/list.html", {
        "page": page, "start": start, "end": end, "filters": request.GET, "qs": params.urlencode(),
        "branches": Branch.objects.all(), "departments": Department.objects.all(), "statuses": AttendanceStatus.choices,
        "pending_corrections": AttendanceCorrection.objects.filter(employee_id__in=ids, status=CorrectionStatus.PENDING).count(),
    })


@role_required(*APPROVE_CORRECTIONS)
def corrections(request):
    ids = visible_employees(request.user).values_list("pk", flat=True)
    items = AttendanceCorrection.objects.filter(employee_id__in=ids).select_related("employee__user", "reviewed_by")
    status = request.GET.get("status", "pending")
    if status:
        items = items.filter(status=status)
    return render(request, "attendance/corrections.html", {"items": items[:100], "status": status})


@role_required(*APPROVE_CORRECTIONS)
@require_POST
def correction_review(request, pk):
    corr = get_object_or_404(
        AttendanceCorrection.objects.filter(employee__in=visible_employees(request.user)).select_related("employee__user"), pk=pk
    )
    approve = request.POST.get("decision") == "approve"
    try:
        apply_correction(corr, request.user, approve, request.POST.get("note", ""))
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("attendance:corrections")
    verb = "approved" if approve else "rejected"
    log(f"attendance.correction_{verb}", request=request, target=corr.employee.employee_number, detail=f"date={corr.date}")
    notifications.notify(corr.employee.user, f"Attendance correction {verb}", f"Your correction for {corr.date:%d %b %Y} was {verb}.",
                         Notification.Category.CORRECTION, "/my/requests/")
    messages.success(request, f"Correction {verb}.")
    return redirect("attendance:corrections")
