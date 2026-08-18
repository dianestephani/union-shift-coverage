from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path("login/", views.login_view, name="login"),

    # App
    path("", views.dashboard, name="dashboard"),
    path("roster/", views.roster, name="roster"),
    path("request/new/", views.shift_request_new, name="shift_request_new"),
    path("request/<int:pk>/", views.shift_request_detail, name="shift_request_detail"),
    path("request/<int:pk>/activate/", views.shift_request_activate, name="shift_request_activate"),

    # Responding to a coverage request
    path("responses/<int:pk>/answer/", views.respond_to_shift, name="respond_to_shift"),

    # In-app notifications
    path("notifications/", views.notifications_page, name="notifications_page"),
    path("notifications/poll/", views.notifications_poll, name="notifications_poll"),
    path("notifications/<int:pk>/read/", views.notification_mark_read, name="notification_mark_read"),
]
