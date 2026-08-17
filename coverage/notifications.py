"""
In-app notification helpers.
All notification text lives here so it's easy to edit.
"""

from .models import Employee, Notification, ShiftRequest, ShiftResponse


def notify(
    employee: Employee,
    shift_request: ShiftRequest,
    message: str,
    action_response: ShiftResponse | None = None,
) -> Notification:
    """Create an in-app notification for `employee`."""
    return Notification.objects.create(
        employee=employee,
        shift_request=shift_request,
        action_response=action_response,
        message=message,
    )


# ---------------------------------------------------------------------------
# Message templates
# ---------------------------------------------------------------------------

def msg_coverage_request(requester_name: str, day: str, date: str, time: str) -> str:
    return (
        f"{requester_name} is looking for shift coverage for {day}, {date} "
        f"from {time}. Respond using the buttons below to let them know if "
        f"you're available."
    )


def msg_covered_confirmation(coverer_name: str, requester_name: str, day: str, date: str, time: str) -> str:
    return (
        f"{coverer_name} has agreed to cover the shift for {requester_name} on "
        f"{day} {date}, from {time}. Please contact management directly to confirm the change."
    )


def msg_declined_notification(decliner_name: str, date: str) -> str:
    return f"{decliner_name} has declined the shift on {date}."
