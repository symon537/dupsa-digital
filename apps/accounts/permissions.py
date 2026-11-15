"""Role-based access control. All checks run on the server."""
from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .models import Role

SUPER = Role.SUPER_ADMIN
DIRECTOR = Role.DIRECTOR
HR = Role.HR_MANAGER
BRANCH = Role.BRANCH_MANAGER
SUPERVISOR = Role.SUPERVISOR
EMPLOYEE = Role.EMPLOYEE

# Capability groups (who may do what)
MANAGE_EMPLOYEES = (SUPER, HR)
MANAGE_ORG = (SUPER, HR)  # departments, branches, shifts, QR rotation
VIEW_STAFF = (SUPER, DIRECTOR, HR, BRANCH, SUPERVISOR)
VIEW_ATTENDANCE = VIEW_STAFF
APPROVE_LEAVE = (SUPER, HR, BRANCH)
APPROVE_CORRECTIONS = (SUPER, HR, BRANCH)
VIEW_REPORTS = VIEW_STAFF
VIEW_QR = (SUPER, HR, BRANCH)
MANAGE_USERS = (SUPER,)
VIEW_AUDIT = (SUPER, HR)
MANAGE_SETTINGS = (SUPER,)
SEND_ANNOUNCEMENTS = (SUPER, HR)


def has_role(user, roles):
    return user.is_authenticated and user.is_active and user.role in roles


def role_required(*roles):
    """View decorator: login required and role must be in ``roles``."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if request.user.role not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


class RoleRequiredMixin(LoginRequiredMixin):
    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if request.user.role not in self.allowed_roles:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


# ------------------------------------------------------------------ scoping
def visible_branches(user):
    """Branches this user is allowed to see."""
    from apps.branches.models import Branch

    qs = Branch.objects.all()
    if user.role in (SUPER, DIRECTOR, HR):
        return qs
    if user.role == BRANCH:
        return qs.filter(manager=user)
    if user.role == SUPERVISOR:
        ids = visible_employees(user).values_list("branch_id", flat=True)
        return qs.filter(pk__in=set(ids))
    if user.has_profile:
        return qs.filter(pk=user.employee_profile.branch_id)
    return qs.none()


def visible_employees(user):
    """Employee profiles this user is allowed to see."""
    from apps.employees.models import EmployeeProfile

    qs = EmployeeProfile.objects.select_related("user", "department", "position", "branch")
    if user.role in (SUPER, DIRECTOR, HR):
        return qs
    if user.role == BRANCH:
        return qs.filter(branch__manager=user)
    if user.role == SUPERVISOR:
        return qs.filter(supervisor=user)
    return qs.filter(user=user)
