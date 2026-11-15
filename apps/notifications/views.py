from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.accounts.permissions import SEND_ANNOUNCEMENTS, role_required
from apps.audit.services import log
from apps.branches.models import Branch
from apps.core.forms import BootstrapForm

from . import services
from .models import Notification


class AnnouncementForm(BootstrapForm):
    title = forms.CharField(max_length=120)
    message = forms.CharField(max_length=400, widget=forms.Textarea(attrs={"rows": 3}))
    branch = forms.ModelChoiceField(queryset=Branch.objects.all(), required=False, empty_label="All branches")


@login_required
def notification_list(request):
    qs = Notification.objects.filter(user=request.user)
    if request.GET.get("filter") == "unread":
        qs = qs.filter(is_read=False)
    page = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {
        "page": page, "can_announce": request.user.role in SEND_ANNOUNCEMENTS, "filter": request.GET.get("filter", ""),
    })


@login_required
@require_POST
def mark_read(request, pk):
    n = get_object_or_404(Notification, pk=pk, user=request.user)
    n.is_read = True
    n.save(update_fields=["is_read"])
    nxt = request.POST.get("next") or n.link or "notifications:list"
    if nxt.startswith("/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect("notifications:list")


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    messages.success(request, "All notifications marked as read.")
    nxt = request.POST.get("next", "")
    if nxt.startswith("/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect("notifications:list")


@role_required(*SEND_ANNOUNCEMENTS)
def announce(request):
    form = AnnouncementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        users = User.objects.filter(is_active=True, employee_profile__isnull=False)
        branch = form.cleaned_data["branch"]
        if branch:
            users = users.filter(employee_profile__branch=branch)
        n = services.notify_many(users, form.cleaned_data["title"], form.cleaned_data["message"], Notification.Category.ANNOUNCEMENT)
        log("announcement.sent", request=request, target=form.cleaned_data["title"], detail=f"{n} recipient(s)")
        messages.success(request, f"Announcement sent to {n} employee(s).")
        return redirect("notifications:list")
    return render(request, "generic_form.html", {"form": form, "title": "Send HR announcement", "back": "notifications:list",
                                                  "submit_label": "Send announcement"})
