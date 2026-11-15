from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/holidays/", views.holidays, name="holidays"),
    path("settings/holidays/<int:pk>/delete/", views.holiday_delete, name="holiday_delete"),
]
