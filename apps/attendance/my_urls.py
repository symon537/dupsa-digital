from django.urls import path

from . import my_views as v

app_name = "my"

urlpatterns = [
    path("", v.home, name="home"),
    path("scan/", v.scan, name="scan"),
    path("records/", v.records, name="records"),
    path("requests/", v.requests_page, name="requests"),
    path("requests/leave/<int:pk>/cancel/", v.leave_cancel, name="leave_cancel"),
    path("profile/", v.profile_page, name="profile"),
    path("notifications/", v.notifications_page, name="notifications"),
]
