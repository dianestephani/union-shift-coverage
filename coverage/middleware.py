from zoneinfo import ZoneInfo

from django.utils import timezone


class EmployeeTimezoneMiddleware:
    """
    Activates the logged-in employee's preferred timezone for the duration
    of the request, so DateTimeField values (notification/event timestamps)
    render in their local time instead of the server's default (TIME_ZONE).

    Must run after AuthenticationMiddleware, since it needs request.user.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        employee = getattr(request.user, "employee", None) if request.user.is_authenticated else None
        if employee:
            timezone.activate(ZoneInfo(employee.timezone))
        else:
            timezone.deactivate()
        return self.get_response(request)
