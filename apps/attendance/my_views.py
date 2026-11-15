"""Employee mobile interface (/my/...)."""
from datetime import timedelta
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.services import log
from apps.leaves.forms import LeaveApplicationForm
from apps.leaves.models import LeaveApplication, LeaveStatus
from apps.leaves.services import LeaveError, balances_for, cancel_application, submit_application
from apps.notifications import services as notifications
from apps.notifications.models import Notification
from apps.shifts.models import get_shift_for

from .forms import CorrectionForm
from .models import AttendanceCorrection, AttendanceRecord


def employee_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.has_profile:
            messages.info(request, "Your account has no employee profile, so the mobile attendance page is not available.")
            return redirect("core:home")
        request.profile = request.user.employee_profile
        return view(request, *args, **kwargs)

    return wrapper


@employee_required
def home(request):
    profile = request.profile
    today = timezone.localdate()
    record = AttendanceRecord.objects.filter(employee=profile, date=today).select_related("branch").first()
    shift = get_shift_for(profile, today)
    return render(request, "mobile/home.html", {
        "profile": profile, "record": record, "shift": shift, "today": today, "nav": "home",
    })


@employee_required
def scan(request):
    """Landing page for QR codes scanned with the phone's own camera app (…/my/scan/?t=TOKEN)."""
    return render(request, "mobile/scan.html", {"profile": request.profile, "token": request.GET.get("t", ""), "nav": "home"})


@employee_required
def records(request):
    qs = AttendanceRecord.objects.filter(employee=request.profile).select_related("branch")
    page = Paginator(qs, 15).get_page(request.GET.get("page"))
    since = timezone.localdate().replace(day=1)
    month = qs.filter(date__gte=since, clock_in__isnull=False)
    summary = {
        "days": month.count(),
        "late": month.filter(status="late").count(),
        "minutes": sum(r.worked_minutes for r in month),
    }
    summary["hours"] = f"{summary['minutes'] // 60} h {summary['minutes'] % 60:02d} m"
    return render(request, "mobile/records.html", {"page": page, "summary": summary, "nav": "records"})


@employee_required
def requests_page(request):
    profile = request.profile
    leave_form = LeaveApplicationForm(profile=profile, prefix="l")
    corr_form = CorrectionForm(profile=profile, prefix="c")
    if request.method == "POST":
        if "submit_leave" in request.POST:
            leave_form = LeaveApplicationForm(request.POST, request.FILES, profile=profile, prefix="l")
            if leave_form.is_valid():
                d = leave_form.cleaned_data
                try:
                    submit_application(profile, d["leave_type"], d["start_date"], d["end_date"], d.get("reason", ""), d.get("document"))
                    messages.success(request, "Leave request submitted.")
                    return redirect("my:requests")
                except LeaveError as exc:
                    leave_form.add_error(None, str(exc))
        elif "submit_correction" in request.POST:
            corr_form = CorrectionForm(request.POST, profile=profile, prefix="c")
            if corr_form.is_valid():
                corr = corr_form.save(commit=False)
                corr.employee = profile
                corr.save()
                log("attendance.correction_requested", user=request.user, target=profile.employee_number, detail=f"date={corr.date}")
                notifications.notify_many(
                    notifications.managers_of(profile) + list(notifications.hr_users()), f"Correction request: {profile.full_name}",
                    f"For {corr.date:%d %b %Y}: {corr.reason[:100]}", Notification.Category.CORRECTION, "/attendance/corrections/")
                messages.success(request, "Correction request submitted.")
                return redirect("my:requests")
    return render(request, "mobile/requests.html", {
        "leave_form": leave_form, "corr_form": corr_form, "nav": "requests",
        "balances": balances_for(profile, timezone.localdate().year),
        "leaves": LeaveApplication.objects.filter(employee=profile).select_related("leave_type")[:15],
        "corrections": AttendanceCorrection.objects.filter(employee=profile)[:10],
    })


@employee_required
@require_POST
def leave_cancel(request, pk):
    app = get_object_or_404(LeaveApplication, pk=pk, employee=request.profile)
    try:
        cancel_application(app)
        log("leave.cancelled", user=request.user, target=request.profile.employee_number, detail=f"{app.start_date}..{app.end_date}")
        messages.success(request, "Leave request cancelled.")
    except LeaveError as exc:
        messages.error(request, str(exc))
    return redirect("my:requests")


@employee_required
def profile_page(request):
    return render(request, "mobile/profile.html", {"profile": request.profile, "nav": "profile"})


@employee_required
def notifications_page(request):
    items = Notification.objects.filter(user=request.user)[:50]
    return render(request, "mobile/notifications.html", {"items": items, "nav": "home"})
