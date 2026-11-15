from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("", views.attendance_list, name="list"),
    path("corrections/", views.corrections, name="corrections"),
    path("corrections/<int:pk>/review/", views.correction_review, name="correction_review"),
]
