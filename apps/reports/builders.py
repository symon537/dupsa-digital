"""Report data builders. Each returns a dict: title, subtitle, columns, rows."""
from collections import defaultdict
from datetime import date, timedelta

from django.utils import timezone

from apps.accounts.permissions import visible_employees
from apps.attendance.models import AttendanceRecord, AttendanceStatus
from apps.core.models import CompanySettings, Holiday
from apps.leaves.models import LeaveApplication, LeaveStatus

REPORT_TYPES = [
    ("daily", "Daily attendance"),
    ("weekly", "Weekly attendance"),
    ("monthly", "Monthly attendance"),
    ("annual", "Annual attendance"),
    ("employee", "Employee attendance (detail)"),
    ("branch", "Branch attendance"),
    ("department", "Department attendance"),
    ("late", "Late arrivals"),
    ("absenteeism", "Absenteeism"),
    ("hours", "Working hours"),
    ("overtime", "Overtime"),
    ("leave", "Leave"),
]


def hm(minutes):
    h, m = divmod(int(minutes or 0), 60)
    return f"{h}:{m:02d}"


def t(dt):
    return timezone.localtime(dt).strftime("%H:%M") if dt else "-"


def period_for(rtype, start):
    if rtype == "weekly":
        s = start - timedelta(days=start.weekday())
        return s, s + timedelta(days=6)
    if rtype == "monthly":
        nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return start.replace(day=1), nxt - timedelta(days=1)
    if rtype == "annual":
        return date(start.year, 1, 1), date(start.year, 12, 31)
    return start, start


def employee_queryset(user, branch=None, department=None, employee=None):
    qs = visible_employees(user)
    if branch:
        qs = qs.filter(branch_id=branch)
    if department:
        qs = qs.filter(department_id=department)
    if employee:
        qs = qs.filter(pk=employee)
    return qs.order_by("employee_number")


def per_employee_summary(employees, start, end):
    """Day-by-day evaluation of expected working days vs attendance for every employee."""
    today = timezone.localdate()
    end_eval = min(end, today)
    working = set(CompanySettings.get().working_day_list)
    ids = [e.pk for e in employees]
    holidays = set(Holiday.objects.filter(date__range=(start, end), branch__isnull=True).values_list("date", flat=True))
    recs = defaultdict(dict)
    for r in AttendanceRecord.objects.filter(employee_id__in=ids, date__range=(start, end)):
        recs[r.employee_id][r.date] = r
    leave_days = defaultdict(set)
    for a in LeaveApplication.objects.filter(employee_id__in=ids, status=LeaveStatus.APPROVED, start_date__lte=end, end_date__gte=start):
        d = max(a.start_date, start)
        while d <= min(a.end_date, end):
            leave_days[a.employee_id].add(d)
            d += timedelta(days=1)
    out = {}
    for e in employees:
        s = dict(expected=0, present=0, late=0, absent=0, leave=0, minutes=0, overtime=0, absent_dates=[])
        d = max(start, e.employment_date)
        while d <= end_eval:
            r = recs[e.pk].get(d)
            is_work = d.weekday() in working and d not in holidays
            if r and r.clock_in:
                s["present"] += 1
                s["late"] += 1 if r.status == AttendanceStatus.LATE else 0
                s["minutes"] += r.worked_minutes
                s["overtime"] += r.overtime_minutes
                s["expected"] += 1 if is_work else 0
            elif is_work:
                s["expected"] += 1
                if d in leave_days[e.pk]:
                    s["leave"] += 1
                else:
                    s["absent"] += 1
                    s["absent_dates"].append(d)
            d += timedelta(days=1)
        out[e.pk] = s
    return out


def _subtitle(start, end, user_branch_name=""):
    return f"{start:%d %b %Y}" if start == end else f"{start:%d %b %Y} to {end:%d %b %Y}"


def build_report(user, rtype, start, end, branch=None, department=None, employee=None):
    employees = list(employee_queryset(user, branch, department, employee))
    if rtype in ("weekly", "monthly", "annual", "daily"):
        start, end = period_for(rtype, start)
    label = dict(REPORT_TYPES).get(rtype, "Report")
    base = {"title": label, "subtitle": _subtitle(start, end), "start": start, "end": end, "type": rtype}

    if rtype == "daily":
        day_records = {r.employee_id: r for r in AttendanceRecord.objects.filter(
            employee_id__in=[e.pk for e in employees], date=start).select_related("branch")}
        summary = per_employee_summary(employees, start, end)
        rows = []
        for e in employees:
            r = day_records.get(e.pk)
            if r and r.clock_in:
                rows.append([e.employee_number, e.full_name, e.department.name if e.department else "-",
                             r.branch.name if r.branch else e.branch.name, t(r.clock_in), t(r.clock_out),
                             hm(r.worked_minutes), r.get_status_display()])
            else:
                st = "On leave" if summary[e.pk]["leave"] else ("Absent" if summary[e.pk]["absent"] else "Not a working day")
                rows.append([e.employee_number, e.full_name, e.department.name if e.department else "-", e.branch.name, "-", "-", "-", st])
        base.update(columns=["Emp No", "Employee", "Department", "Branch", "Clock in", "Clock out", "Hours", "Status"], rows=rows)

    elif rtype in ("weekly", "monthly", "annual", "hours", "overtime", "absenteeism"):
        summary = per_employee_summary(employees, start, end)
        rows = []
        for e in employees:
            s = summary[e.pk]
            common = [e.employee_number, e.full_name, e.branch.name, e.department.name if e.department else "-"]
            if rtype == "hours":
                avg = s["minutes"] / s["present"] if s["present"] else 0
                rows.append(common + [s["present"], hm(s["minutes"]), hm(avg)])
            elif rtype == "overtime":
                if s["overtime"]:
                    rows.append(common + [hm(s["overtime"])])
            elif rtype == "absenteeism":
                if s["absent"]:
                    dates = ", ".join(d.strftime("%d/%m") for d in s["absent_dates"][:12]) + (" ..." if len(s["absent_dates"]) > 12 else "")
                    rows.append(common + [s["absent"], dates])
            else:
                rows.append(common + [s["expected"], s["present"], s["late"], s["absent"], s["leave"], hm(s["minutes"]), hm(s["overtime"])])
        cols = {
            "hours": ["Days worked", "Total hours", "Avg per day"],
            "overtime": ["Overtime (h:mm)"],
            "absenteeism": ["Days absent", "Dates"],
        }.get(rtype, ["Working days", "Present", "Late", "Absent", "On leave", "Hours", "Overtime"])
        base.update(columns=["Emp No", "Employee", "Branch", "Department"] + cols, rows=rows)

    elif rtype in ("employee", "late"):
        qs = AttendanceRecord.objects.filter(employee_id__in=[e.pk for e in employees], date__range=(start, end)).select_related(
            "employee__user", "employee__department", "branch")
        if rtype == "late":
            qs = qs.filter(status=AttendanceStatus.LATE)
        qs = qs.order_by("date", "employee__employee_number")
        rows = [[r.date.strftime("%d %b %Y"), r.employee.employee_number, r.employee.full_name,
                 r.branch.name if r.branch else "-", t(r.clock_in), t(r.clock_out), hm(r.worked_minutes),
                 r.late_minutes, hm(r.overtime_minutes), r.get_status_display()] for r in qs]
        base.update(columns=["Date", "Emp No", "Employee", "Branch", "Clock in", "Clock out", "Hours", "Late (min)", "Overtime", "Status"], rows=rows)

    elif rtype in ("branch", "department"):
        summary = per_employee_summary(employees, start, end)
        groups = defaultdict(lambda: dict(n=0, expected=0, present=0, late=0, absent=0, leave=0, minutes=0))
        for e in employees:
            key = e.branch.name if rtype == "branch" else (e.department.name if e.department else "Unassigned")
            g = groups[key]
            g["n"] += 1
            for k in ("expected", "present", "late", "absent", "leave", "minutes"):
                g[k] += summary[e.pk][k]
        rows = []
        for name in sorted(groups):
            g = groups[name]
            pct = f"{g['present'] / g['expected'] * 100:.1f}%" if g["expected"] else "-"
            rows.append([name, g["n"], g["expected"], g["present"], g["late"], g["absent"], g["leave"], hm(g["minutes"]), pct])
        base.update(columns=[rtype.capitalize(), "Employees", "Expected days", "Present", "Late", "Absent", "On leave", "Hours", "Attendance %"], rows=rows)

    elif rtype == "leave":
        qs = LeaveApplication.objects.filter(
            employee_id__in=[e.pk for e in employees], start_date__lte=end, end_date__gte=start
        ).select_related("employee__user", "leave_type").order_by("start_date")
        rows = [[a.employee.employee_number, a.employee.full_name, a.leave_type.name, a.start_date.strftime("%d %b %Y"),
                 a.end_date.strftime("%d %b %Y"), a.days, a.get_status_display()] for a in qs]
        base.update(columns=["Emp No", "Employee", "Leave type", "From", "To", "Days", "Status"], rows=rows)
    else:
        base.update(columns=[], rows=[])
    return base
