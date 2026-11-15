from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.permissions import MANAGE_ORG, VIEW_STAFF, role_required
from apps.audit.services import log
from apps.core.forms import BootstrapModelForm

from .models import Department, Position


class DepartmentForm(BootstrapModelForm):
    class Meta:
        model = Department
        fields = ["name", "code", "description", "is_active"]

    def clean_code(self):
        return self.cleaned_data["code"].strip().upper()


class PositionForm(BootstrapModelForm):
    class Meta:
        model = Position
        fields = ["name", "department", "is_active"]


@role_required(*VIEW_STAFF)
def index(request):
    can_manage = request.user.role in MANAGE_ORG
    dform, pform = DepartmentForm(prefix="d"), PositionForm(prefix="p")
    if request.method == "POST":
        if not can_manage:
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied
        if "save_department" in request.POST:
            dform = DepartmentForm(request.POST, prefix="d")
            if dform.is_valid():
                d = dform.save()
                log("department.created", request=request, target=d.name)
                messages.success(request, f"Department '{d.name}' added.")
                return redirect("departments:index")
        elif "save_position" in request.POST:
            pform = PositionForm(request.POST, prefix="p")
            if pform.is_valid():
                p = pform.save()
                log("position.created", request=request, target=p.name)
                messages.success(request, f"Position '{p.name}' added.")
                return redirect("departments:index")
    departments = Department.objects.annotate(
        staff=Count("employees", filter=Q(employees__status__in=["active", "probation"]))
    )
    positions = Position.objects.select_related("department")
    return render(request, "departments/index.html", {
        "departments": departments, "positions": positions, "dform": dform, "pform": pform, "can_manage": can_manage,
    })


@role_required(*MANAGE_ORG)
def department_edit(request, pk):
    obj = get_object_or_404(Department, pk=pk)
    form = DepartmentForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        log("department.updated", request=request, target=obj.name)
        messages.success(request, "Department updated.")
        return redirect("departments:index")
    return render(request, "generic_form.html", {"form": form, "title": f"Edit department: {obj.name}", "back": "departments:index"})


@role_required(*MANAGE_ORG)
def position_edit(request, pk):
    obj = get_object_or_404(Position, pk=pk)
    form = PositionForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        log("position.updated", request=request, target=obj.name)
        messages.success(request, "Position updated.")
        return redirect("departments:index")
    return render(request, "generic_form.html", {"form": form, "title": f"Edit position: {obj.name}", "back": "departments:index"})
