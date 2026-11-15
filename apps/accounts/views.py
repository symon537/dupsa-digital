from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from apps.audit.services import log

from . import security
from .forms import LoginForm, UserForm
from .models import User
from .permissions import MANAGE_USERS, role_required


class MalkiaLoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        username = request.POST.get("username", "")
        ip = security.client_ip(request)
        if security.is_locked(username, ip):
            log("auth.locked_out", request=request, username=username, ip=ip, detail="Sign-in blocked after repeated failures")
            form = self.get_form()
            form.is_bound = True
            form.add_error(None, "Too many failed attempts. Please wait 15 minutes and try again.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        security.clear(self.request.POST.get("username", ""), security.client_ip(self.request))
        if not form.cleaned_data.get("remember_me"):
            self.request.session.set_expiry(0)  # expires when the browser closes
        else:
            self.request.session.set_expiry(60 * 60 * 24 * 14)
        return response

    def form_invalid(self, form):
        security.register_failure(self.request.POST.get("username", ""), security.client_ip(self.request))
        return super().form_invalid(form)


class ChangePasswordView(auth_views.PasswordChangeView):
    template_name = "accounts/change_password.html"
    success_url = reverse_lazy("accounts:change_password_done")

    def form_valid(self, form):
        log("auth.password_changed", request=self.request, detail="User changed own password")
        return super().form_valid(form)


@login_required
def change_password_done(request):
    messages.success(request, "Your password was changed successfully.")
    return redirect("core:home")


# ------------------------------------------------------- user management
@role_required(*MANAGE_USERS)
def user_list(request):
    q = request.GET.get("q", "").strip()
    role = request.GET.get("role", "")
    users = User.objects.all()
    if q:
        from django.db.models import Q

        users = users.filter(Q(username__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))
    if role:
        users = users.filter(role=role)
    from .models import Role

    return render(request, "accounts/user_list.html", {"users": users, "q": q, "role": role, "roles": Role.choices})


@role_required(*MANAGE_USERS)
def user_edit(request, pk=None):
    user = get_object_or_404(User, pk=pk) if pk else None
    old_role = user.role if user else None
    form = UserForm(request.POST or None, instance=user)
    if request.method == "POST" and form.is_valid():
        if user and user.pk == request.user.pk and (not form.cleaned_data["is_active"] or form.cleaned_data["role"] != user.role):
            messages.error(request, "You cannot deactivate yourself or change your own role.")
        else:
            saved = form.save()
            log("user.created" if pk is None else "user.updated", request=request, target=saved.username,
                detail=f"role={saved.role}; active={saved.is_active}")
            if old_role and old_role != saved.role:
                log("permission.role_changed", request=request, target=saved.username, detail=f"{old_role} -> {saved.role}")
            messages.success(request, f"User {saved.username} saved.")
            return redirect("accounts:user_list")
    return render(request, "accounts/user_form.html", {"form": form, "edited": user})


@role_required(*MANAGE_USERS)
@require_POST
def user_toggle(request, pk):
    user = get_object_or_404(User, pk=pk)
    if user.pk == request.user.pk:
        messages.error(request, "You cannot deactivate your own account.")
    else:
        user.is_active = not user.is_active
        user.save(update_fields=["is_active"])
        log("user.activated" if user.is_active else "user.deactivated", request=request, target=user.username)
        messages.success(request, f"{user.username} is now {'active' if user.is_active else 'deactivated'}.")
    return redirect("accounts:user_list")
