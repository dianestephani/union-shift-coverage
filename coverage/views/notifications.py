from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..models import Notification, ShiftRequest, ShiftResponse
from ..notifications import prune_notifications
from .common import get_logged_in_employee, login_required_employee, safe_next_url


@login_required_employee
def notifications_page(request):
    employee = get_logged_in_employee(request)
    prune_notifications(employee)
    notifications = Notification.objects.filter(employee=employee).select_related(
        "shift_request", "shift_request__requester", "action_response"
    )
    return render(request, "coverage/notifications.html", {
        "employee": employee,
        "notifications": notifications,
    })


@login_required_employee
def notifications_poll(request):
    employee = get_logged_in_employee(request)
    prune_notifications(employee)
    unread = Notification.objects.filter(
        employee=employee, read_at__isnull=True
    ).select_related("shift_request", "action_response")

    def actionable_response_id(n):
        if (
            n.action_response_id
            and n.action_response.answer == ShiftResponse.Answer.PENDING
            and n.shift_request.status == ShiftRequest.Status.SEARCHING
        ):
            return n.action_response_id
        return None

    return JsonResponse({
        "unread_count": unread.count(),
        "notifications": [
            {
                "id": n.pk,
                "message": n.message,
                "shift_request_id": n.shift_request_id,
                "action_response_id": actionable_response_id(n),
                "created_at": n.created_at.isoformat(),
            }
            for n in unread[:20]
        ],
    })


@login_required_employee
@require_POST
def notification_mark_read(request, pk):
    employee = get_logged_in_employee(request)
    Notification.objects.filter(pk=pk, employee=employee, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    if request.POST.get("next"):
        return redirect(safe_next_url(request, "dashboard"))
    return JsonResponse({"ok": True})
