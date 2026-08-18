from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..coverage_service import handle_response
from ..models import Notification, ShiftResponse
from .common import get_logged_in_employee, login_required_employee, safe_next_url


@login_required_employee
@require_POST
def respond_to_shift(request, pk):
    employee = get_logged_in_employee(request)
    shift_response = get_object_or_404(ShiftResponse, pk=pk, employee=employee)
    answer = request.POST.get("answer", "")
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    try:
        handle_response(shift_response, employee, answer)
        Notification.objects.filter(
            action_response=shift_response, read_at__isnull=True
        ).update(read_at=timezone.now())
        if is_ajax:
            return JsonResponse({"ok": True})
        messages.success(request, "Your response was recorded.")
    except ValueError as exc:
        if is_ajax:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        messages.error(request, str(exc))

    return redirect(safe_next_url(request, "dashboard"))
