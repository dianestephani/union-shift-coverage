from zoneinfo import ZoneInfo

from django.utils import timezone

from . import time_format


class EmployeePreferencesMiddleware:
    """
    Activates the logged-in employee's display preferences for the duration
    of the request:
      - timezone, so DateTimeField values (notification/event timestamps)
        render in their local time instead of the server's default (TIME_ZONE)
      - military_time, so times render as 14:00 instead of 2:00 PM where
        the app chooses to honor it (see coverage.time_format)

    Must run after AuthenticationMiddleware, since it needs request.user.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        employee = getattr(request.user, "employee", None) if request.user.is_authenticated else None
        if employee:
            timezone.activate(ZoneInfo(employee.timezone))
            time_format.activate(employee.military_time)
        else:
            timezone.deactivate()
            time_format.deactivate()
        return self.get_response(request)
