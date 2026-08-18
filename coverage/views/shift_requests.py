from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..coverage_service import cancel_request, start_coverage_search
from ..forms import ShiftRequestForm
from ..models import CoverageEvent, ShiftRequest
from .common import get_logged_in_employee, login_required_employee, logger


@login_required_employee
def shift_request_new(request):
    employee = get_logged_in_employee(request)
    form = ShiftRequestForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        action = request.POST.get("action")  # "save_draft" or "find_coverage"

        sr = form.save(commit=False)
        sr.requester = employee
        sr.status = ShiftRequest.Status.DRAFT
        sr.save()

        CoverageEvent.objects.create(
            shift_request=sr,
            event_type=CoverageEvent.EventType.REQUEST_CREATED,
            employee=employee,
            message="Draft created.",
        )

        if action == "find_coverage":
            try:
                start_coverage_search(sr)
                messages.success(request, "Coverage search started! We'll notify the roster for you.")
            except Exception as exc:
                logger.exception("Error starting coverage search")
                messages.error(request, f"Could not start search: {exc}")
        else:
            messages.success(request, "Draft saved.")

        return redirect("dashboard")

    return render(request, "coverage/shift_request_form.html", {
        "form": form,
        "employee": employee,
    })


@login_required_employee
def shift_request_detail(request, pk):
    employee = get_logged_in_employee(request)
    sr = get_object_or_404(
        ShiftRequest.objects.select_related("current_candidate", "covered_by", "requester"),
        pk=pk,
    )
    if sr.requester_id != employee.id and not employee.is_manager:
        raise Http404
    events = sr.events.select_related("employee").order_by("created_at")
    responses = sr.responses.select_related("employee").order_by("asked_at")
    return render(request, "coverage/shift_request_detail.html", {
        "employee": employee,
        "sr": sr,
        "events": events,
        "responses": responses,
    })


@login_required_employee
def shift_request_activate(request, pk):
    """Activate a DRAFT request (Find Coverage from the detail page)."""
    employee = get_logged_in_employee(request)
    sr = get_object_or_404(
        ShiftRequest, pk=pk, requester=employee, status=ShiftRequest.Status.DRAFT
    )
    if request.method == "POST":
        try:
            start_coverage_search(sr)
            messages.success(request, "Coverage search started!")
        except Exception as exc:
            logger.exception("Error activating coverage search")
            messages.error(request, f"Error: {exc}")
    return redirect("shift_request_detail", pk=pk)


@login_required_employee
@require_POST
def shift_request_cancel(request, pk):
    """Requester withdraws a DRAFT/SEARCHING request."""
    employee = get_logged_in_employee(request)
    sr = get_object_or_404(ShiftRequest, pk=pk, requester=employee)
    try:
        cancel_request(sr, employee)
        messages.success(request, "Request cancelled.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("shift_request_detail", pk=pk)
