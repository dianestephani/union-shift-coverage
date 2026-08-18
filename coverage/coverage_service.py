"""
Core coverage state machine.

start_coverage_search(sr)                       – notify the first roster candidate
handle_response(shift_response, employee, answer) – process a YES / NO button response
cancel_request(sr, employee)                      – requester withdraws a DRAFT/SEARCHING request
"""

import logging
from django.utils import timezone

from .models import Employee, ShiftRequest, ShiftResponse, CoverageEvent
from .notifications import (
    notify,
    msg_coverage_request,
    msg_covered_confirmation,
    msg_declined_notification,
    msg_cancelled_notification,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log(shift_request, event_type, employee=None, message=""):
    CoverageEvent.objects.create(
        shift_request=shift_request,
        event_type=event_type,
        employee=employee,
        message=message,
    )


def _shift_context(sr: ShiftRequest):
    """Return (day, date, time) display strings for a ShiftRequest."""
    return sr.day_display(), sr.date_display(), sr.time_display()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_coverage_search(shift_request: ShiftRequest) -> None:
    """
    Transition a DRAFT request to SEARCHING and notify the first candidate.
    The first candidate is the employee immediately below the requester
    in seniority (higher seniority_rank value).
    """
    if shift_request.status != ShiftRequest.Status.DRAFT:
        raise ValueError("Only DRAFT requests can be activated.")

    first_candidate = shift_request.requester.get_next_in_roster()
    if first_candidate is None:
        shift_request.status = ShiftRequest.Status.UNCOVERED
        shift_request.save(update_fields=["status", "updated_at"])
        _log(shift_request, CoverageEvent.EventType.UNCOVERED,
             message="No employees below requester in roster.")
        return

    shift_request.status = ShiftRequest.Status.SEARCHING
    shift_request.current_candidate = first_candidate
    shift_request.save(update_fields=["status", "current_candidate", "updated_at"])
    _log(shift_request, CoverageEvent.EventType.REQUEST_ACTIVATED)

    _ask_candidate(shift_request, first_candidate)


def _ask_candidate(shift_request: ShiftRequest, candidate: Employee) -> None:
    """Create a ShiftResponse row and send the in-app notification."""
    response, _ = ShiftResponse.objects.get_or_create(
        shift_request=shift_request,
        employee=candidate,
        defaults={"answer": ShiftResponse.Answer.PENDING},
    )
    day, date, time = _shift_context(shift_request)
    body = msg_coverage_request(shift_request.requester.name, day, date, time)
    notify(candidate, shift_request, body, action_response=response)
    _log(
        shift_request,
        CoverageEvent.EventType.NOTIFICATION_SENT,
        employee=candidate,
        message=body,
    )


def handle_response(shift_response: ShiftResponse, employee: Employee, answer: str) -> str:
    """
    Called when an employee presses a YES/NO button on one of their
    notifications. `shift_response` is the specific pending ask being
    answered; `answer` is "YES" or "NO".
    """
    answer_upper = answer.strip().upper()
    if answer_upper not in ("YES", "NO"):
        raise ValueError(f"Unrecognised answer: {answer!r}")

    if shift_response.employee_id != employee.id:
        raise ValueError("This response does not belong to the logged-in employee.")

    if shift_response.answer != ShiftResponse.Answer.PENDING:
        raise ValueError("This request has already been answered.")

    sr = shift_response.shift_request
    if sr.status != ShiftRequest.Status.SEARCHING:
        # The requester cancelled it (or it otherwise stopped being active)
        # after this ask went out but before it got answered.
        raise ValueError("This request is no longer looking for coverage.")

    _log(sr, CoverageEvent.EventType.RESPONSE_RECEIVED, employee=employee, message=answer_upper)

    shift_response.answer = answer_upper
    shift_response.answered_at = timezone.now()
    shift_response.save(update_fields=["answer", "answered_at"])

    if answer_upper == "YES":
        return _handle_yes(sr, employee)
    else:
        return _handle_no(sr, employee)


def _handle_yes(sr: ShiftRequest, employee: Employee) -> str:
    day, date, time = _shift_context(sr)
    confirmation = msg_covered_confirmation(
        employee.name, sr.requester.name, day, date, time
    )
    # Notify both the coverer and the requester
    notify(employee, sr, confirmation)
    notify(sr.requester, sr, confirmation)

    sr.status = ShiftRequest.Status.COVERED
    sr.covered_by = employee
    sr.current_candidate = None
    sr.save(update_fields=["status", "covered_by", "current_candidate", "updated_at"])
    _log(sr, CoverageEvent.EventType.COVERED, employee=employee, message=confirmation)

    return f"Shift covered by {employee.name}."


def _find_next_untried_candidate(sr: ShiftRequest, employee: Employee) -> Employee | None:
    """
    The next active employee below `employee` in seniority who hasn't
    already answered this request. Fetches the remaining roster and the
    set of already-answered employees in one query each, and walks them in
    Python — instead of one query per skipped candidate (as a
    `while ...: candidate = candidate.get_next_in_roster()` loop would do),
    which could mean O(k) DB round-trips for a single decline on a roster
    with many already-answered candidates.
    """
    already_answered_ids = set(
        ShiftResponse.objects.filter(shift_request=sr)
        .exclude(answer=ShiftResponse.Answer.PENDING)
        .values_list("employee_id", flat=True)
    )
    remaining_roster = Employee.objects.filter(
        seniority_rank__gt=employee.seniority_rank,
        is_active=True,
    ).order_by("seniority_rank")

    for candidate in remaining_roster:
        if candidate.id not in already_answered_ids:
            return candidate
    return None


def _handle_no(sr: ShiftRequest, employee: Employee) -> str:
    day, date, time = _shift_context(sr)
    decline_msg = msg_declined_notification(employee.name, date)
    notify(sr.requester, sr, decline_msg)
    _log(sr, CoverageEvent.EventType.NOTIFICATION_SENT, employee=sr.requester, message=decline_msg)

    next_candidate = _find_next_untried_candidate(sr, employee)

    if next_candidate is None:
        sr.status = ShiftRequest.Status.UNCOVERED
        sr.current_candidate = None
        sr.save(update_fields=["status", "current_candidate", "updated_at"])
        _log(sr, CoverageEvent.EventType.UNCOVERED, message="Roster exhausted.")
        return "Roster exhausted – no coverage found."

    sr.current_candidate = next_candidate
    sr.save(update_fields=["current_candidate", "updated_at"])
    _ask_candidate(sr, next_candidate)
    return f"Moved to next candidate: {next_candidate.name}."


def cancel_request(sr: ShiftRequest, employee: Employee) -> None:
    """
    The requester withdraws a request that hasn't been resolved yet. Only
    DRAFT and SEARCHING requests can be cancelled — COVERED/UNCOVERED/
    already-CANCELLED are all terminal states.
    """
    if sr.requester_id != employee.id:
        raise ValueError("Only the requester can cancel this request.")

    if sr.status not in (ShiftRequest.Status.DRAFT, ShiftRequest.Status.SEARCHING):
        raise ValueError(f"Can't cancel a request that's already {sr.get_status_display()}.")

    was_searching = sr.status == ShiftRequest.Status.SEARCHING
    current_candidate = sr.current_candidate

    sr.status = ShiftRequest.Status.CANCELLED
    sr.current_candidate = None
    sr.save(update_fields=["status", "current_candidate", "updated_at"])
    _log(sr, CoverageEvent.EventType.CANCELLED, employee=employee, message=f"Cancelled by {employee.name}.")

    if was_searching and current_candidate:
        day, date, time = _shift_context(sr)
        notify(
            current_candidate, sr,
            msg_cancelled_notification(sr.requester.name, day, date, time),
        )
