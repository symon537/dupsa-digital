from django.urls import path

from . import views

app_name = "departments"

urlpatterns = [
    path("", views.index, name="index"),
    path("<int:pk>/edit/", views.department_edit, name="department_edit"),
    path("positions/<int:pk>/edit/", views.position_edit, name="position_edit"),
]
