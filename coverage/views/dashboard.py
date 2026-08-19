from django.conf import settings
from django.contrib.auth import login as auth_login
from django.http import Http404
from django.shortcuts import redirect, render

from ..models import Employee, ShiftRequest, ShiftResponse
from .common import get_logged_in_employee, login_required_employee, paginate


def login_view(request):
    if get_logged_in_employee(request):
        return redirect("dashboard")
    return render(request, "coverage/login.html", {
        "demo_login_enabled": settings.DEMO_LOGIN_ENABLED,
    })


def demo_login(request):
    """
    Lets a visitor skip Google OAuth and log straight in as the seeded demo
    Employee — see DEMO_LOGIN_ENABLED in settings.py. 404s rather than
    redirecting when disabled, matching this app's usual "don't reveal it
    exists" pattern for gated pages (see manager_required in common.py).
    """
    if not settings.DEMO_LOGIN_ENABLED:
        raise Http404
    employee = Employee.objects.select_related("user").filter(
        email__iexact=settings.DEMO_EMPLOYEE_EMAIL, user__isnull=False
    ).first()
    if not employee:
        raise Http404
    # Refuse to grant this publicly-reachable login button access to Django
    # admin, regardless of how the demo Employee/User end up configured —
    # is_manager (app-level) is fine here, is_staff/is_superuser never are.
    if employee.user.is_staff or employee.user.is_superuser:
        raise Http404
    auth_login(request, employee.user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("dashboard")


@login_required_employee
def dashboard(request):
    employee = get_logged_in_employee(request)
    my_requests = ShiftRequest.objects.filter(requester=employee).select_related(
        "current_candidate", "covered_by"
    ).order_by("-created_at")
    my_pending_responses = ShiftResponse.objects.filter(
        employee=employee,
        answer=ShiftResponse.Answer.PENDING,
        shift_request__status=ShiftRequest.Status.SEARCHING,
    ).select_related("shift_request", "shift_request__requester")
    my_covering = ShiftResponse.objects.filter(
        employee=employee, answer=ShiftResponse.Answer.YES
    ).select_related("shift_request", "shift_request__requester").order_by("-answered_at")
    my_declined = ShiftResponse.objects.filter(
        employee=employee, answer=ShiftResponse.Answer.NO
    ).select_related("shift_request", "shift_request__requester").order_by("-answered_at")
    return render(request, "coverage/dashboard.html", {
        "employee": employee,
        "my_requests_page": paginate(request, my_requests),
        "my_pending_responses": my_pending_responses,
        "my_covering": my_covering,
        "my_declined": my_declined,
    })
