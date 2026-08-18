import logging

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .coverage_service import handle_response, start_coverage_search
from .forms import ShiftRequestForm
from .models import CoverageEvent, Employee, Notification, ShiftRequest, ShiftResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _get_logged_in_employee(request):
    if not request.user.is_authenticated:
        return None
    return getattr(request.user, "employee", None)


def login_required_employee(view_func):
    """Simple decorator – redirects to login if no linked employee."""
    from functools import wraps

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not _get_logged_in_employee(request):
            return redirect("login")
        return view_func(request, *args, **kwargs)

    return wrapper


def login_view(request):
    if _get_logged_in_employee(request):
        return redirect("dashboard")
    return render(request, "coverage/login.html")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required_employee
def dashboard(request):
    employee = _get_logged_in_employee(request)
    my_requests = ShiftRequest.objects.filter(requester=employee).select_related(
        "current_candidate", "covered_by"
    ).order_by("-created_at")
    my_pending_responses = ShiftResponse.objects.filter(
        employee=employee, answer=ShiftResponse.Answer.PENDING
    ).select_related("shift_request", "shift_request__requester")
    return render(request, "coverage/dashboard.html", {
        "employee": employee,
        "my_requests": my_requests,
        "my_pending_responses": my_pending_responses,
    })


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------

@login_required_employee
def roster(request):
    employee = _get_logged_in_employee(request)
    employees = Employee.objects.all().order_by("seniority_rank")
    return render(request, "coverage/roster.html", {
        "employee": employee,
        "employees": employees,
    })


# ---------------------------------------------------------------------------
# Shift request views
# ---------------------------------------------------------------------------

@login_required_employee
def shift_request_new(request):
    employee = _get_logged_in_employee(request)
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
    employee = _get_logged_in_employee(request)
    sr = get_object_or_404(
        ShiftRequest.objects.select_related("current_candidate", "covered_by"),
        pk=pk,
        requester=employee,
    )
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
    employee = _get_logged_in_employee(request)
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


# ---------------------------------------------------------------------------
# Responding to a coverage request (replaces the SMS reply flow)
# ---------------------------------------------------------------------------

@login_required_employee
@require_POST
def respond_to_shift(request, pk):
    employee = _get_logged_in_employee(request)
    shift_response = get_object_or_404(ShiftResponse, pk=pk, employee=employee)
    answer = request.POST.get("answer", "")

    try:
        handle_response(shift_response, employee, answer)
        messages.success(request, "Your response was recorded.")
    except ValueError as exc:
        messages.error(request, str(exc))

    next_url = request.POST.get("next") or "dashboard"
    return redirect(next_url)


# ---------------------------------------------------------------------------
# In-app notifications (polling)
# ---------------------------------------------------------------------------

@login_required_employee
def notifications_poll(request):
    employee = _get_logged_in_employee(request)
    unread = Notification.objects.filter(
        employee=employee, read_at__isnull=True
    ).select_related("shift_request", "action_response")

    return JsonResponse({
        "unread_count": unread.count(),
        "notifications": [
            {
                "id": n.pk,
                "message": n.message,
                "shift_request_id": n.shift_request_id,
                "action_response_id": n.action_response_id,
                "created_at": n.created_at.isoformat(),
            }
            for n in unread[:20]
        ],
    })


@login_required_employee
@require_POST
def notification_mark_read(request, pk):
    employee = _get_logged_in_employee(request)
    Notification.objects.filter(pk=pk, employee=employee, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    return JsonResponse({"ok": True})
