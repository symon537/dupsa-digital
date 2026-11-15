from django.urls import path

from . import api

urlpatterns = [
    path("attendance/clock-in/", api.ClockInView.as_view(), name="api_clock_in"),
    path("attendance/clock-out/", api.ClockOutView.as_view(), name="api_clock_out"),
    path("attendance/qr-check/", api.QRCheckView.as_view(), name="api_qr_check"),
    path("attendance/today/", api.TodayView.as_view(), name="api_today"),
    path("dashboard/charts/", api.DashboardChartsView.as_view(), name="api_dashboard_charts"),
]
