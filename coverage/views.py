import logging

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .coverage_service import cancel_request, handle_response, start_coverage_search
from .forms import EmployeeSettingsForm, ShiftRequestForm
from .models import CoverageEvent, Employee, Notification, ShiftRequest, ShiftResponse
from .notifications import prune_notifications

logger = logging.getLogger(__name__)


def _safe_next_url(request, fallback):
    """
    Only redirect to a `next` value if it points back at this site.
    Without this check, a `next` param crafted by an attacker (this is a
    plain POST field, not something Django signs) could send a logged-in
    user off to an external phishing page.
    """
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return fallback


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


def manager_required(view_func):
    """
    Redirects to login if not logged in, and 404s (rather than a 403 that
    would reveal the page exists) if the employee isn't a manager.
    """
    from functools import wraps

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        employee = _get_logged_in_employee(request)
        if not employee:
            return redirect("login")
        if not employee.is_manager:
            raise Http404
        return view_func(request, *args, **kwargs)

    return wrapper


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
        "my_requests": my_requests,
        "my_pending_responses": my_pending_responses,
        "my_covering": my_covering,
        "my_declined": my_declined,
    })


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@login_required_employee
def settings_page(request):
    employee = _get_logged_in_employee(request)
    form = EmployeeSettingsForm(request.POST or None, instance=employee)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Settings saved.")
        return redirect("settings")

    return render(request, "coverage/settings.html", {
        "employee": employee,
        "form": form,
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
# Manager dashboard
# ---------------------------------------------------------------------------

@manager_required
def manager_dashboard(request):
    employee = _get_logged_in_employee(request)
    open_requests = ShiftRequest.objects.filter(
        status__in=[ShiftRequest.Status.DRAFT, ShiftRequest.Status.SEARCHING]
    ).select_related("requester", "current_candidate").order_by("-created_at")
    employees = Employee.objects.all().order_by("seniority_rank")
    recent_events = CoverageEvent.objects.select_related(
        "shift_request", "shift_request__requester", "employee"
    ).order_by("-created_at")[:25]
    return render(request, "coverage/manager_dashboard.html", {
        "employee": employee,
        "open_requests": open_requests,
        "employees": employees,
        "recent_events": recent_events,
    })


@manager_required
def manager_employee_detail(request, pk):
    employee = _get_logged_in_employee(request)
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
        "requests": requests,
        "responses": responses,
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


@login_required_employee
@require_POST
def shift_request_cancel(request, pk):
    """Requester withdraws a DRAFT/SEARCHING request."""
    employee = _get_logged_in_employee(request)
    sr = get_object_or_404(ShiftRequest, pk=pk, requester=employee)
    try:
        cancel_request(sr, employee)
        messages.success(request, "Request cancelled.")
    except ValueError as exc:
        messages.error(request, str(exc))
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

    return redirect(_safe_next_url(request, "dashboard"))


# ---------------------------------------------------------------------------
# In-app notifications (polling)
# ---------------------------------------------------------------------------

@login_required_employee
def notifications_page(request):
    employee = _get_logged_in_employee(request)
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
    employee = _get_logged_in_employee(request)
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
    employee = _get_logged_in_employee(request)
    Notification.objects.filter(pk=pk, employee=employee, read_at__isnull=True).update(
        read_at=timezone.now()
    )
    if request.POST.get("next"):
        return redirect(_safe_next_url(request, "dashboard"))
    return JsonResponse({"ok": True})
