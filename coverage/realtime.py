"""
Real-time notification delivery over Django Channels. Keeps "how do we
reach a specific employee's open browser tab(s)" in one place: the group
naming (used by both the consumer joining a group and notify() pushing to
it) and the push helper itself.
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def group_name_for_employee(employee_id: int) -> str:
    return f"employee-{employee_id}-notifications"


def push_notification(employee_id: int, payload: dict) -> None:
    """
    Send `payload` to every open browser tab for the employee with this id,
    if any are connected. No-ops if the channel layer isn't configured
    (e.g. running under a plain WSGI server without ASGI/Channels set up).
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        group_name_for_employee(employee_id),
        {"type": "notification.message", "payload": payload},
    )
