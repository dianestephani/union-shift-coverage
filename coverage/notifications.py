"""
In-app notification helpers.
All notification text lives here so it's easy to edit.
"""

from datetime import timedelta

from django.utils import timezone

from .models import Employee, Notification, ShiftRequest, ShiftResponse
from .realtime import push_notification

NOTIFICATION_RETENTION = timedelta(hours=24)
MAX_NOTIFICATIONS_PER_EMPLOYEE = 10


def notify(
    employee: Employee,
    shift_request: ShiftRequest,
    message: str,
    action_response: ShiftResponse | None = None,
) -> Notification:
    """Create an in-app notification for `employee` and push it in real time."""
    notification = Notification.objects.create(
        employee=employee,
        shift_request=shift_request,
        action_response=action_response,
        message=message,
    )
    prune_notifications(employee)

    action_response_id = None
    if action_response and action_response.answer == ShiftResponse.Answer.PENDING:
        action_response_id = action_response.pk

    push_notification(employee.id, {
        "id": notification.pk,
        "message": notification.message,
        "shift_request_id": notification.shift_request_id,
        "action_response_id": action_response_id,
        "created_at": notification.created_at.isoformat(),
        "unread_count": Notification.objects.filter(
            employee=employee, read_at__isnull=True
        ).count(),
    })

    return notification


def prune_notifications(employee: Employee) -> None:
    """
    Delete notifications older than 24h, and cap storage at the 10 most
    recent. Notifications still awaiting a Yes/No response are exempt from
    both rules — otherwise a flood of unrelated notifications (or just
    time passing) could silently hide the one thing an employee still
    owes an answer to, even though the request itself is still pending.
    """
    actionable = Notification.objects.filter(
        employee=employee,
        action_response__isnull=False,
        action_response__answer=ShiftResponse.Answer.PENDING,
        action_response__shift_request__status=ShiftRequest.Status.SEARCHING,
    )

    cutoff = timezone.now() - NOTIFICATION_RETENTION
    Notification.objects.filter(employee=employee, created_at__lt=cutoff).exclude(
        pk__in=actionable
    ).delete()

    keep_ids = set(
        Notification.objects.filter(employee=employee).order_by(
            "-created_at"
        ).values_list("pk", flat=True)[:MAX_NOTIFICATIONS_PER_EMPLOYEE]
    ) | set(actionable.values_list("pk", flat=True))
    Notification.objects.filter(employee=employee).exclude(pk__in=keep_ids).delete()


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


def msg_cancelled_notification(requester_name: str, day: str, date: str, time: str) -> str:
    return (
        f"{requester_name} cancelled their shift coverage request for {day}, "
        f"{date} from {time}. No response needed."
    )
