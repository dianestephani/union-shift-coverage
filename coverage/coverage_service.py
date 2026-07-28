"""
Core coverage state machine.

ask_next_candidate()       – send the request SMS to the next person in roster
handle_response(phone, answer) – process an inbound YES / NO / UNSURE reply
"""

import logging
from django.utils import timezone

from .models import Employee, ShiftRequest, ShiftResponse, CoverageEvent
from .sms import (
    send_sms,
    msg_coverage_request,
    msg_covered_confirmation,
    msg_declined_notification,
    msg_unsure_notification,
    msg_someone_covered_notify_unsure,
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
    Transition a DRAFT request to SEARCHING and send the first ask.
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
    """Create a ShiftResponse row and send the request SMS."""
    ShiftResponse.objects.get_or_create(
        shift_request=shift_request,
        employee=candidate,
        defaults={"answer": ShiftResponse.Answer.PENDING},
    )
    day, date, time = _shift_context(shift_request)
    body = msg_coverage_request(shift_request.requester.name, day, date, time)
    send_sms(candidate.get_phone_e164(), body)
    _log(
        shift_request,
        CoverageEvent.EventType.SMS_SENT,
        employee=candidate,
        message=body,
    )


def handle_response(from_phone: str, raw_answer: str) -> str:
    """
    Called from the Twilio webhook with the sender's phone number and
    their reply text. Returns a plain-text acknowledgement (not sent as SMS,
    but useful for logging/debugging).
    """
    answer_upper = raw_answer.strip().upper()

    # Normalise synonyms
    if answer_upper not in ("YES", "NO", "UNSURE"):
        return f"Unrecognised reply '{raw_answer}' from {from_phone} – ignored."

    # Resolve employee
    try:
        employee = Employee.objects.get(phone_number=from_phone, is_active=True)
    except Employee.DoesNotExist:
        logger.warning("SMS from unknown number %s", from_phone)
        return f"No active employee found for {from_phone}."

    # Find the open ShiftResponse for this employee
    pending_response = (
        ShiftResponse.objects.filter(
            employee=employee,
            answer=ShiftResponse.Answer.PENDING,
            shift_request__status=ShiftRequest.Status.SEARCHING,
        )
        .select_related("shift_request__requester")
        .order_by("asked_at")
        .first()
    )

    if pending_response is None:
        # Check if they're responding UNSURE → YES/NO after someone else covered
        return _maybe_handle_unsure_resolution(employee, answer_upper, from_phone)

    sr = pending_response.shift_request
    _log(sr, CoverageEvent.EventType.SMS_RECEIVED, employee=employee, message=answer_upper)

    pending_response.answer = answer_upper
    pending_response.answered_at = timezone.now()
    pending_response.save(update_fields=["answer", "answered_at"])

    if answer_upper == "YES":
        return _handle_yes(sr, employee)
    elif answer_upper == "NO":
        return _handle_no(sr, employee)
    else:  # UNSURE
        return _handle_unsure(sr, employee)


def _handle_yes(sr: ShiftRequest, employee: Employee) -> str:
    day, date, time = _shift_context(sr)
    confirmation = msg_covered_confirmation(
        employee.name, sr.requester.name, day, date, time
    )
    # Notify both the coverer and the requester
    send_sms(employee.get_phone_e164(), confirmation)
    send_sms(sr.requester.get_phone_e164(), confirmation)

    sr.status = ShiftRequest.Status.COVERED
    sr.covered_by = employee
    sr.current_candidate = None
    sr.save(update_fields=["status", "covered_by", "current_candidate", "updated_at"])
    _log(sr, CoverageEvent.EventType.COVERED, employee=employee, message=confirmation)

    # Notify any UNSURE respondents that someone covered and they need to resolve
    _notify_unsure_of_coverage(sr, employee)

    return f"Shift covered by {employee.name}."


def _handle_no(sr: ShiftRequest, employee: Employee) -> str:
    day, date, time = _shift_context(sr)
    decline_msg = msg_declined_notification(employee.name, date)
    send_sms(sr.requester.get_phone_e164(), decline_msg)
    _log(sr, CoverageEvent.EventType.SMS_SENT, employee=sr.requester, message=decline_msg)

    # Advance to next candidate
    next_candidate = employee.get_next_in_roster()

    # Skip candidates who have already been asked (e.g. UNSURE who already responded)
    while next_candidate and ShiftResponse.objects.filter(
        shift_request=sr,
        employee=next_candidate,
    ).exclude(answer=ShiftResponse.Answer.PENDING).exists():
        next_candidate = next_candidate.get_next_in_roster()

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


def _handle_unsure(sr: ShiftRequest, employee: Employee) -> str:
    day, date, time = _shift_context(sr)
    unsure_msg = msg_unsure_notification(employee.name, day, date)
    send_sms(sr.requester.get_phone_e164(), unsure_msg)
    _log(sr, CoverageEvent.EventType.SMS_SENT, employee=sr.requester, message=unsure_msg)

    # Continue down the roster in parallel
    next_candidate = employee.get_next_in_roster()

    while next_candidate and ShiftResponse.objects.filter(
        shift_request=sr,
        employee=next_candidate,
    ).exclude(answer=ShiftResponse.Answer.PENDING).exists():
        next_candidate = next_candidate.get_next_in_roster()

    if next_candidate is None:
        # Roster exhausted but UNSURE people are still pending – that's OK,
        # we wait for them to resolve.
        _log(sr, CoverageEvent.EventType.UNCOVERED,
             message="Roster exhausted below UNSURE respondents. Awaiting UNSURE resolution.")
    else:
        sr.current_candidate = next_candidate
        sr.save(update_fields=["current_candidate", "updated_at"])
        _ask_candidate(sr, next_candidate)

    return f"{employee.name} replied UNSURE – continuing down roster."


def _notify_unsure_of_coverage(sr: ShiftRequest, coverer: Employee) -> None:
    """
    Once a shift is covered, tell everyone who replied UNSURE that they need
    to provide a final YES or NO.
    """
    unsure_responses = sr.responses.filter(answer=ShiftResponse.Answer.UNSURE)
    if not unsure_responses.exists():
        return

    date = sr.date_display()
    body = msg_someone_covered_notify_unsure(coverer.name, sr.requester.name, date)

    # Notify requester too
    send_sms(sr.requester.get_phone_e164(), body)
    _log(sr, CoverageEvent.EventType.SMS_SENT, employee=sr.requester, message=body)

    for resp in unsure_responses:
        send_sms(resp.employee.get_phone_e164(), body)
        _log(sr, CoverageEvent.EventType.SMS_SENT, employee=resp.employee, message=body)


def _maybe_handle_unsure_resolution(
    employee: Employee, answer_upper: str, from_phone: str
) -> str:
    """
    Handle a YES/NO reply from someone who previously said UNSURE,
    after the shift was already covered.
    """
    unsure_resp = (
        ShiftResponse.objects.filter(
            employee=employee,
            answer=ShiftResponse.Answer.UNSURE,
        )
        .select_related("shift_request")
        .order_by("-asked_at")
        .first()
    )

    if unsure_resp is None:
        return f"No pending UNSURE response found for {employee.name} ({from_phone})."

    sr = unsure_resp.shift_request
    _log(sr, CoverageEvent.EventType.SMS_RECEIVED, employee=employee,
         message=f"UNSURE resolution: {answer_upper}")

    if answer_upper == "YES":
        unsure_resp.answer = ShiftResponse.Answer.UNSURE_YES
    else:
        unsure_resp.answer = ShiftResponse.Answer.UNSURE_NO

    unsure_resp.answered_at = timezone.now()
    unsure_resp.save(update_fields=["answer", "answered_at"])

    _log(sr, CoverageEvent.EventType.UNSURE_RESOLVED, employee=employee,
         message=answer_upper)

    return f"{employee.name} resolved UNSURE to {answer_upper}."
