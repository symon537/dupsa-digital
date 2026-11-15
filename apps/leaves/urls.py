from django.urls import path

from . import views

app_name = "leaves"

urlpatterns = [
    path("", views.leave_list, name="list"),
    path("<int:pk>/review/", views.leave_review, name="review"),
    path("calendar/", views.leave_calendar, name="calendar"),
    path("types/", views.leave_types, name="types"),
    path("types/<int:pk>/edit/", views.leave_type_edit, name="type_edit"),
]
