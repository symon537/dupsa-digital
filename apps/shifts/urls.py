from django.urls import path

from . import views

app_name = "shifts"

urlpatterns = [
    path("", views.shift_list, name="list"),
    path("new/", views.shift_edit, name="create"),
    path("<int:pk>/edit/", views.shift_edit, name="edit"),
    path("assign/", views.shift_assign, name="assign"),
    path("assignments/<int:pk>/delete/", views.assignment_delete, name="assignment_delete"),
]
