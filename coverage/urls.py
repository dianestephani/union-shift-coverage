from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # App
    path("", views.dashboard, name="dashboard"),
    path("request/new/", views.shift_request_new, name="shift_request_new"),
    path("request/<int:pk>/", views.shift_request_detail, name="shift_request_detail"),
    path("request/<int:pk>/activate/", views.shift_request_activate, name="shift_request_activate"),

    # Twilio webhook
    path("sms/inbound/", views.twilio_webhook, name="twilio_webhook"),
]
