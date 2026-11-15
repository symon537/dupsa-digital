from datetime import date, timedelta

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from apps.accounts.permissions import VIEW_AUDIT, role_required

from .models import AuditLog


@role_required(*VIEW_AUDIT)
def audit_list(request):
    qs = AuditLog.objects.select_related("user")
    q = request.GET.get("q", "").strip()
    action = request.GET.get("action", "")
    if q:
        qs = qs.filter(Q(username__icontains=q) | Q(target__icontains=q) | Q(detail__icontains=q))
    if action:
        qs = qs.filter(action__startswith=action)
    for key, lookup in (("from", "created_at__date__gte"), ("to", "created_at__date__lte")):
        try:
            qs = qs.filter(**{lookup: date.fromisoformat(request.GET.get(key, ""))})
        except ValueError:
            pass
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    groups = ["auth", "employee", "attendance", "branch", "shift", "leave", "user", "permission", "qr", "settings"]
    return render(request, "audit/list.html", {"page": page, "filters": request.GET, "groups": groups, "qs": params.urlencode()})
