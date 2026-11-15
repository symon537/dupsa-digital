from django.urls import path

from . import views

app_name = "branches"

urlpatterns = [
    path("", views.branch_list, name="list"),
    path("new/", views.branch_edit, name="create"),
    path("<int:pk>/edit/", views.branch_edit, name="edit"),
    path("<int:pk>/toggle/", views.branch_toggle, name="toggle"),
    path("qr/", views.qr_list, name="qr_list"),
    path("<int:pk>/qr.png", views.qr_image, name="qr_image"),
    path("<int:pk>/qr/poster/", views.qr_poster, name="qr_poster"),
    path("<int:pk>/qr/rotate/", views.qr_rotate, name="qr_rotate"),
]
