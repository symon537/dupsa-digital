import calendar
from datetime import date, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.permissions import APPROVE_LEAVE, MANAGE_ORG, VIEW_STAFF, role_required, visible_employees
from apps.audit.services import log

from .forms import LeaveTypeForm
from .models import LeaveApplication, LeaveStatus, LeaveType
from .services import LeaveError, review_application


@role_required(*VIEW_STAFF)
def leave_list(request):
    ids = visible_employees(request.user).values_list("pk", flat=True)
    qs = LeaveApplication.objects.filter(employee_id__in=ids).select_related("employee__user", "leave_type", "reviewed_by")
    status = request.GET.get("status", "")
    if status:
        qs = qs.filter(status=status)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "leaves/list.html", {
        "page": page, "status": status, "statuses": LeaveStatus.choices,
        "can_review": request.user.role in APPROVE_LEAVE,
    })


@role_required(*APPROVE_LEAVE)
@require_POST
def leave_review(request, pk):
    app = get_object_or_404(LeaveApplication.objects.filter(employee__in=visible_employees(request.user)), pk=pk)
    approve = request.POST.get("decision") == "approve"
    try:
        review_application(app, request.user, approve, request.POST.get("note", ""))
        messages.success(request, f"Leave {'approved' if approve else 'rejected'}.")
    except LeaveError as exc:
        messages.error(request, str(exc))
    return redirect("leaves:list")


@role_required(*VIEW_STAFF)
def leave_calendar(request):
    today = timezone.localdate()
    try:
        year, month = (int(x) for x in request.GET.get("month", f"{today.year}-{today.month}").split("-"))
        first = date(year, month, 1)
    except (ValueError, TypeError):
        first = today.replace(day=1)
    last_day = calendar.monthrange(first.year, first.month)[1]
    last = first.replace(day=last_day)
    ids = visible_employees(request.user).values_list("pk", flat=True)
    apps = LeaveApplication.objects.filter(
        employee_id__in=ids, status=LeaveStatus.APPROVED, start_date__lte=last, end_date__gte=first
    ).select_related("employee__user", "leave_type")
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month):
        row = []
        for d in week:
            names = [f"{a.employee.full_name} ({a.leave_type.name})" for a in apps if a.start_date <= d <= a.end_date]
            row.append({"date": d, "in_month": d.month == first.month, "leaves": names, "today": d == today})
        weeks.append(row)
    prev = (first - timedelta(days=1)).replace(day=1)
    nxt = (last + timedelta(days=1)).replace(day=1)
    return render(request, "leaves/calendar.html", {
        "weeks": weeks, "month": first, "prev": f"{prev.year}-{prev.month}", "next": f"{nxt.year}-{nxt.month}",
    })


@role_required(*MANAGE_ORG)
def leave_types(request):
    form = LeaveTypeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        lt = form.save()
        log("leave_type.created", request=request, target=lt.name)
        messages.success(request, "Leave type added.")
        return redirect("leaves:types")
    return render(request, "leaves/types.html", {"types": LeaveType.objects.all(), "form": form})


@role_required(*MANAGE_ORG)
def leave_type_edit(request, pk):
    obj = get_object_or_404(LeaveType, pk=pk)
    form = LeaveTypeForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        log("leave_type.updated", request=request, target=obj.name)
        messages.success(request, "Leave type updated.")
        return redirect("leaves:types")
    return render(request, "generic_form.html", {"form": form, "title": f"Edit leave type: {obj.name}", "back": "leaves:types"})
