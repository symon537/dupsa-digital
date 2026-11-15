import csv

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.permissions import MANAGE_EMPLOYEES, VIEW_STAFF, role_required, visible_employees
from apps.attendance.models import AttendanceRecord
from apps.audit.services import log
from apps.branches.models import Branch
from apps.departments.models import Department
from apps.leaves.services import balances_for

from .forms import EmployeeForm
from .models import EmploymentStatus


def _filtered(request):
    qs = visible_employees(request.user)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q) | Q(employee_number__icontains=q)
            | Q(phone__icontains=q) | Q(user__email__icontains=q) | Q(user__username__icontains=q)
        )
    for param, field in (("branch", "branch_id"), ("department", "department_id"), ("status", "status")):
        val = request.GET.get(param, "")
        if val:
            qs = qs.filter(**{field: val})
    return qs.order_by("employee_number")


@role_required(*VIEW_STAFF)
def employee_list(request):
    qs = _filtered(request)
    if request.GET.get("export") in ("csv", "xlsx"):
        return _export(request, qs, request.GET["export"])
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return render(request, "employees/list.html", {
        "page": page, "branches": Branch.objects.all(), "departments": Department.objects.all(),
        "statuses": EmploymentStatus.choices, "filters": request.GET, "qs": params.urlencode(),
        "can_manage": request.user.role in MANAGE_EMPLOYEES,
    })


EXPORT_HEADERS = ["Employee No", "Full name", "Gender", "Phone", "Email", "Department", "Position", "Branch",
                  "Employment date", "Status", "Emergency contact", "Emergency phone"]


def _export_rows(qs):
    for e in qs:
        yield [e.employee_number, e.full_name, e.get_gender_display(), e.phone, e.user.email,
               e.department.name if e.department else "", e.position.name if e.position else "", e.branch.name,
               e.employment_date.isoformat(), e.get_status_display(), e.emergency_contact_name, e.emergency_contact_phone]


def _export(request, qs, fmt):
    log("employees.exported", request=request, detail=f"format={fmt}; rows={qs.count()}")
    if fmt == "csv":
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="employees.csv"'
        w = csv.writer(resp)
        w.writerow(EXPORT_HEADERS)
        w.writerows(_export_rows(qs))
        return resp
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Employees"
    ws.append(EXPORT_HEADERS)
    for row in _export_rows(qs):
        ws.append(row)
    resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="employees.xlsx"'
    wb.save(resp)
    return resp


@role_required(*VIEW_STAFF)
def employee_detail(request, pk):
    emp = get_object_or_404(visible_employees(request.user), pk=pk)
    today = timezone.localdate()
    records = AttendanceRecord.objects.filter(employee=emp).select_related("branch")[:31]
    return render(request, "employees/detail.html", {
        "emp": emp, "records": records, "balances": balances_for(emp, today.year),
        "can_manage": request.user.role in MANAGE_EMPLOYEES,
    })


@role_required(*MANAGE_EMPLOYEES)
def employee_edit(request, pk=None):
    emp = get_object_or_404(EmployeeProfileQS(), pk=pk) if pk else None
    form = EmployeeForm(request.POST or None, request.FILES or None, instance=emp)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        log("employee.created" if pk is None else "employee.updated", request=request, target=saved.employee_number,
            detail=saved.full_name)
        if form.temp_password:
            messages.success(
                request,
                f"Employee created. Username: {saved.user.username} | Temporary password: {form.temp_password} "
                "(shown once - give it to the employee and ask them to change it).",
            )
        else:
            messages.success(request, f"Employee {saved.full_name} saved.")
        return redirect("employees:detail", pk=saved.pk)
    return render(request, "employees/form.html", {"form": form, "emp": emp})


def EmployeeProfileQS():
    from .models import EmployeeProfile

    return EmployeeProfile.objects.select_related("user", "branch", "department", "position")


@role_required(*MANAGE_EMPLOYEES)
@require_POST
def employee_toggle(request, pk):
    emp = get_object_or_404(EmployeeProfileQS(), pk=pk)
    if emp.user_id == request.user.pk:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect("employees:detail", pk=pk)
    if emp.is_active_employee:
        emp.status = EmploymentStatus.TERMINATED
        emp.user.is_active = False
        verb = "deactivated"
    else:
        emp.status = EmploymentStatus.ACTIVE
        emp.user.is_active = True
        verb = "reactivated"
    emp.user.save(update_fields=["is_active"])
    emp.save(update_fields=["status", "updated_at"])
    log(f"employee.{verb}", request=request, target=emp.employee_number, detail=emp.full_name)
    messages.success(request, f"{emp.full_name} was {verb}.")
    return redirect("employees:detail", pk=pk)
