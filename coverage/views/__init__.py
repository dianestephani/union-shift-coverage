"""
Views, split by feature area now that a single views.py had grown to hold
every page in the app (dashboard, roster, manager pages, shift request
CRUD, and the notification endpoints all mixed together).

This __init__ re-exports every view function so `coverage/urls.py` can keep
doing `from . import views` / `views.dashboard` unchanged — callers outside
this package don't need to know it's a package instead of a single module.
"""
from .dashboard import dashboard, login_view
from .settings import settings_page
from .roster import roster
from .manager import manager_dashboard, manager_employee_detail
from .shift_requests import (
    shift_request_new,
    shift_request_detail,
    shift_request_activate,
    shift_request_cancel,
)
from .responses import respond_to_shift
from .notifications import notifications_page, notifications_poll, notification_mark_read

__all__ = [
    "dashboard",
    "login_view",
    "settings_page",
    "roster",
    "manager_dashboard",
    "manager_employee_detail",
    "shift_request_new",
    "shift_request_detail",
    "shift_request_activate",
    "shift_request_cancel",
    "respond_to_shift",
    "notifications_page",
    "notifications_poll",
    "notification_mark_read",
]
