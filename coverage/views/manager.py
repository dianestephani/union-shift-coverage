from django.shortcuts import get_object_or_404, render

from ..models import CoverageEvent, Employee, ShiftRequest, ShiftResponse
from .common import get_logged_in_employee, manager_required, paginate

# Deliberately not paginated: this is a bounded "what just happened" feed,
# not a full activity browser. If that ever needs to change, paginate it
# the same way open_requests below is.
RECENT_ACTIVITY_LIMIT = 25


@manager_required
def manager_dashboard(request):
    employee = get_logged_in_employee(request)
    open_requests = ShiftRequest.objects.filter(
        status__in=[ShiftRequest.Status.DRAFT, ShiftRequest.Status.SEARCHING]
    ).select_related("requester", "current_candidate").order_by("-created_at")
    employees = Employee.objects.all().order_by("seniority_rank")
    recent_events = CoverageEvent.objects.select_related(
        "shift_request", "shift_request__requester", "employee"
    ).order_by("-created_at")[:RECENT_ACTIVITY_LIMIT]
    return render(request, "coverage/manager_dashboard.html", {
        "employee": employee,
        "open_requests_page": paginate(request, open_requests, param="requests_page"),
        "employees": employees,
        "recent_events": recent_events,
    })


@manager_required
def manager_employee_detail(request, pk):
    employee = get_logged_in_employee(request)
    target = get_object_or_404(Employee, pk=pk)
    requests = ShiftRequest.objects.filter(requester=target).select_related(
        "current_candidate", "covered_by"
    ).order_by("-created_at")
    responses = ShiftResponse.objects.filter(employee=target).select_related(
        "shift_request", "shift_request__requester"
    ).order_by("-asked_at")
    return render(request, "coverage/manager_employee_detail.html", {
        "employee": employee,
        "target": target,
        "requests_page": paginate(request, requests, param="requests_page"),
        "responses_page": paginate(request, responses, param="responses_page"),
    })
