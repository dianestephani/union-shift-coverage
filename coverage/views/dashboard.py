from django.shortcuts import redirect, render

from ..models import ShiftRequest, ShiftResponse
from .common import get_logged_in_employee, login_required_employee, paginate


def login_view(request):
    if get_logged_in_employee(request):
        return redirect("dashboard")
    return render(request, "coverage/login.html")


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
