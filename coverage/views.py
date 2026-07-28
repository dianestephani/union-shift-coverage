import logging

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from phonenumber_field.phonenumber import PhoneNumber

from .coverage_service import handle_response, start_coverage_search
from .forms import PhoneLoginForm, ShiftRequestForm
from .models import CoverageEvent, Employee, ShiftRequest

logger = logging.getLogger(__name__)

SESSION_EMPLOYEE_ID = "employee_id"


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _get_logged_in_employee(request):
    employee_id = request.session.get(SESSION_EMPLOYEE_ID)
    if not employee_id:
        return None
    try:
        return Employee.objects.get(pk=employee_id, is_active=True)
    except Employee.DoesNotExist:
        return None


def login_required_employee(view_func):
    """Simple decorator – redirects to login if no session employee."""
    from functools import wraps

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not _get_logged_in_employee(request):
            return redirect("login")
        return view_func(request, *args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------

def login_view(request):
    if _get_logged_in_employee(request):
        return redirect("dashboard")

    form = PhoneLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        raw_phone = form.cleaned_data["phone_number"]

        # Try to parse as E.164 (US default)
        parsed = PhoneNumber.from_string(raw_phone, region="US")
        if not parsed.is_valid():
            form.add_error("phone_number", "Please enter a valid US phone number.")
        else:
            e164 = str(parsed)
            try:
                employee = Employee.objects.get(phone_number=e164, is_active=True)
                request.session[SESSION_EMPLOYEE_ID] = employee.pk
                return redirect("dashboard")
            except Employee.DoesNotExist:
                form.add_error(
                    "phone_number",
                    "No active account found for that number. Please contact your manager.",
                )

    return render(request, "coverage/login.html", {"form": form})


def logout_view(request):
    request.session.flush()
    return redirect("login")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@login_required_employee
def dashboard(request):
    employee = _get_logged_in_employee(request)
    my_requests = ShiftRequest.objects.filter(requester=employee).order_by("-created_at")
    return render(request, "coverage/dashboard.html", {
        "employee": employee,
        "my_requests": my_requests,
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
                messages.success(request, "Coverage search started! We'll text the roster for you.")
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
    sr = get_object_or_404(ShiftRequest, pk=pk, requester=employee)
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
# Twilio inbound SMS webhook
# ---------------------------------------------------------------------------

@csrf_exempt
@require_POST
def twilio_webhook(request):
    """
    Twilio sends a POST with 'From' and 'Body' when an SMS is received.
    We validate the Twilio signature in production; skipped here for simplicity
    but see the README for how to enable it.
    """
    from_number = request.POST.get("From", "")
    body = request.POST.get("Body", "")

    logger.info("Inbound SMS from %s: %r", from_number, body)

    result = handle_response(from_phone=from_number, raw_answer=body)
    logger.info("handle_response result: %s", result)

    # Twilio expects a TwiML response; an empty <Response> means no reply SMS.
    return HttpResponse(
        '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
        content_type="text/xml",
    )
