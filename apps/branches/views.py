import io

import qrcode
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Role, User
from apps.accounts.permissions import MANAGE_ORG, VIEW_QR, VIEW_STAFF, role_required, visible_branches
from apps.audit.services import log
from apps.core.forms import BootstrapModelForm

from .models import Branch, OfficeQRCode


class BranchForm(BootstrapModelForm):
    class Meta:
        model = Branch
        fields = ["name", "code", "address", "latitude", "longitude", "radius_m", "manager", "phone", "email", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["manager"].queryset = User.objects.filter(is_active=True).exclude(role=Role.EMPLOYEE)
        self.fields["manager"].required = False

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


@role_required(*VIEW_STAFF)
def branch_list(request):
    today = timezone.localdate()
    branches = visible_branches(request.user).select_related("manager").annotate(
        staff=Count("employees", filter=Q(employees__status__in=["active", "probation"]), distinct=True),
        present_today=Count(
            "employees",
            filter=Q(employees__attendance_records__date=today, employees__attendance_records__clock_in__isnull=False),
            distinct=True,
        ),
    )
    return render(request, "branches/list.html", {"branches": branches, "can_manage": request.user.role in MANAGE_ORG})


@role_required(*MANAGE_ORG)
def branch_edit(request, pk=None):
    branch = get_object_or_404(Branch, pk=pk) if pk else None
    form = BranchForm(request.POST or None, instance=branch)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        saved.ensure_qr()
        log("branch.created" if pk is None else "branch.updated", request=request, target=saved.name,
            detail=f"lat={saved.latitude}, lon={saved.longitude}, radius={saved.radius_m} m")
        messages.success(request, f"Branch '{saved.name}' saved.")
        return redirect("branches:list")
    return render(request, "generic_form.html", {
        "form": form, "title": f"Edit branch: {branch.name}" if branch else "Add branch", "back": "branches:list",
        "hint": "Tip: open Google Maps, right-click the shop entrance and copy the latitude/longitude shown.",
    })


@role_required(*MANAGE_ORG)
@require_POST
def branch_toggle(request, pk):
    b = get_object_or_404(Branch, pk=pk)
    b.is_active = not b.is_active
    b.save(update_fields=["is_active"])
    log("branch.activated" if b.is_active else "branch.deactivated", request=request, target=b.name)
    messages.success(request, f"{b.name} is now {'active' if b.is_active else 'deactivated'}.")
    return redirect("branches:list")


# ------------------------------------------------------ QR management
@role_required(*VIEW_QR)
def qr_list(request):
    branches = list(visible_branches(request.user).filter(is_active=True))
    if request.user.role in MANAGE_ORG:
        for b in branches:
            b.ensure_qr()
    for b in branches:
        b.current_qr = b.active_qr
    return render(request, "branches/qr_list.html", {"branches": branches, "can_manage": request.user.role in MANAGE_ORG})


def _branch_for_qr(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    if not visible_branches(request.user).filter(pk=branch.pk).exists():
        raise PermissionDenied
    return branch


def _qr_png(url):
    img = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    img.add_data(url)
    img.make(fit=True)
    out = io.BytesIO()
    img.make_image(fill_color="#650D35", back_color="white").save(out, format="PNG")
    return out.getvalue()


@role_required(*VIEW_QR)
def qr_image(request, pk):
    branch = _branch_for_qr(request, pk)
    qr = branch.active_qr
    if qr is None:
        if request.user.role not in MANAGE_ORG:
            raise PermissionDenied
        qr = branch.ensure_qr()
    resp = HttpResponse(_qr_png(qr.scan_url), content_type="image/png")
    resp["Cache-Control"] = "private, no-store"
    return resp


@role_required(*VIEW_QR)
def qr_poster(request, pk):
    branch = _branch_for_qr(request, pk)
    return render(request, "branches/qr_poster.html", {"branch": branch, "qr": branch.active_qr})


@role_required(*MANAGE_ORG)
@require_POST
def qr_rotate(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    qr = OfficeQRCode.issue(branch, user=request.user)
    log("qr.rotated", request=request, target=branch.name, detail=f"New QR valid until {qr.expires_at:%Y-%m-%d}")
    messages.success(request, f"New QR code issued for {branch.name}. Print and replace the old poster; the old code no longer works.")
    return redirect("branches:qr_list")
