"""Dashboard statistics and chart data. Every number comes from the database."""
from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.accounts.permissions import visible_branches, visible_employees
from apps.core.models import CompanySettings, Holiday
from apps.employees.models import ACTIVE_STATUSES
from apps.leaves.models import LeaveApplication, LeaveStatus

from .models import AttendanceRecord, AttendanceStatus


def active_employees(user):
    return visible_employees(user).filter(status__in=ACTIVE_STATUSES, user__is_active=True)


def on_leave_ids(employee_qs, day):
    return set(
        LeaveApplication.objects.filter(
            employee__in=employee_qs, status=LeaveStatus.APPROVED, start_date__lte=day, end_date__gte=day
        ).values_list("employee_id", flat=True)
    )


def is_company_working_day(day):
    if day.weekday() not in CompanySettings.get().working_day_list:
        return False
    return not Holiday.objects.filter(date=day, branch__isnull=True).exists()


def dashboard_stats(user, day=None):
    day = day or timezone.localdate()
    employees = active_employees(user)
    ids = list(employees.values_list("pk", flat=True))
    total = len(ids)
    records = AttendanceRecord.objects.filter(employee_id__in=ids, date=day, clock_in__isnull=False)
    present = records.count()
    late = records.filter(status=AttendanceStatus.LATE).count()
    clocked_in = records.filter(clock_out__isnull=True).count()
    leave_ids = on_leave_ids(employees, day)
    on_leave = len(leave_ids - set(records.values_list("employee_id", flat=True)))
    working = is_company_working_day(day)
    absent = max(0, total - present - on_leave) if working else 0
    denominator = total - on_leave
    pct = round(present / denominator * 100, 1) if denominator > 0 and working else 0.0
    return {
        "date": day,
        "total_employees": total,
        "present": present,
        "on_time": present - late,
        "late": late,
        "absent": absent,
        "on_leave": on_leave,
        "clocked_in": clocked_in,
        "branches": visible_branches(user).filter(is_active=True).count(),
        "attendance_pct": pct,
        "working_day": working,
    }


def recent_clock_ins(user, day=None, limit=8):
    day = day or timezone.localdate()
    ids = active_employees(user).values_list("pk", flat=True)
    return (
        AttendanceRecord.objects.filter(employee_id__in=ids, date=day, clock_in__isnull=False)
        .select_related("employee__user", "branch")
        .order_by("-clock_in")[:limit]
    )


def _pct(n, d):
    return round(n / d * 100, 1) if d else 0.0


def chart_data(user, day=None):
    day = day or timezone.localdate()
    employees = active_employees(user)
    ids = list(employees.values_list("pk", flat=True))
    total = len(ids)

    # last 7 days
    days = [day - timedelta(days=i) for i in range(6, -1, -1)]
    present_by_day = dict(
        AttendanceRecord.objects.filter(employee_id__in=ids, date__in=days, clock_in__isnull=False)
        .values_list("date").annotate(n=Count("id")).values_list("date", "n")
    )
    late_by_day = dict(
        AttendanceRecord.objects.filter(employee_id__in=ids, date__in=days, status=AttendanceStatus.LATE)
        .values_list("date").annotate(n=Count("id")).values_list("date", "n")
    )
    trend7 = {
        "labels": [d.strftime("%d %b") for d in days],
        "present": [present_by_day.get(d, 0) for d in days],
        "percent": [_pct(present_by_day.get(d, 0), total) for d in days],
        "late": [late_by_day.get(d, 0) for d in days],
    }

    # last 6 months
    first = day.replace(day=1)
    months = []
    cur = first
    for _ in range(6):
        months.append(cur)
        cur = (cur - timedelta(days=1)).replace(day=1)
    months.reverse()
    monthly = (
        AttendanceRecord.objects.filter(employee_id__in=ids, date__gte=months[0])
        .annotate(m=TruncMonth("date"))
        .values("m")
        .annotate(
            present=Count("id", filter=Q(clock_in__isnull=False)),
            late=Count("id", filter=Q(status=AttendanceStatus.LATE)),
            absent=Count("id", filter=Q(status=AttendanceStatus.ABSENT)),
        )
    )
    mmap = {(r["m"].date() if hasattr(r["m"], "date") else r["m"]).replace(day=1): r for r in monthly}
    trend_month = {
        "labels": [m.strftime("%b %Y") for m in months],
        "present": [mmap.get(m, {}).get("present", 0) for m in months],
        "late": [mmap.get(m, {}).get("late", 0) for m in months],
        "absent": [mmap.get(m, {}).get("absent", 0) for m in months],
    }

    # by branch / by department (today)
    present_ids = set(
        AttendanceRecord.objects.filter(employee_id__in=ids, date=day, clock_in__isnull=False).values_list("employee_id", flat=True)
    )

    def group(field, names):
        rows = {}
        for pk, key in employees.values_list("pk", field):
            rows.setdefault(key, [0, 0])
            rows[key][1] += 1
            if pk in present_ids:
                rows[key][0] += 1
        out = []
        for key, (p, t) in rows.items():
            out.append({"name": names.get(key, "Unassigned"), "present": p, "total": t, "percent": _pct(p, t)})
        return sorted(out, key=lambda r: r["name"])

    from apps.branches.models import Branch
    from apps.departments.models import Department

    by_branch = group("branch_id", dict(Branch.objects.values_list("pk", "name")))
    by_department = group("department_id", dict(Department.objects.values_list("pk", "name")))

    stats = dashboard_stats(user, day)
    donut = {
        "labels": ["On time", "Late", "On leave", "Absent"],
        "values": [stats["on_time"], stats["late"], stats["on_leave"], stats["absent"]],
    }
    return {
        "trend7": trend7,
        "trend_month": trend_month,
        "by_branch": by_branch,
        "by_department": by_department,
        "donut": donut,
        "presence_pct": stats["attendance_pct"],
    }
