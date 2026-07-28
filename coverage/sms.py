"""
Twilio SMS helpers.
All outbound message text lives here so it's easy to edit.
"""

from django.conf import settings
from twilio.rest import Client


def _client():
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)


def send_sms(to: str, body: str) -> None:
    """Send an SMS via Twilio. `to` must be E.164 format, e.g. '+15551234567'."""
    client = _client()
    client.messages.create(
        body=body,
        from_=settings.TWILIO_PHONE_NUMBER,
        to=to,
    )


# ---------------------------------------------------------------------------
# Message templates
# ---------------------------------------------------------------------------

def msg_coverage_request(requester_name: str, day: str, date: str, time: str) -> str:
    return (
        f"{requester_name} is looking for shift coverage for {day}, {date} "
        f"from {time}. Please reply with YES if you are available, NO if you "
        f"are not, and UNSURE if you are interested but need to check your schedule."
    )


def msg_covered_confirmation(coverer_name: str, requester_name: str, day: str, date: str, time: str) -> str:
    return (
        f"{coverer_name} has agreed to cover the shift for {requester_name} on "
        f"{day} {date}, from {time}. Please contact management directly to confirm the change."
    )


def msg_declined_notification(decliner_name: str, date: str) -> str:
    return f"{decliner_name} has declined the shift on {date}."


def msg_unsure_notification(unsure_name: str, day: str, date: str) -> str:
    return (
        f"{unsure_name} is interested in the shift on {day} {date}, "
        f"but will report back later to confirm."
    )


def msg_someone_covered_notify_unsure(
    coverer_name: str, requester_name: str, date: str
) -> str:
    return (
        f"{coverer_name} is available to cover the shift from {requester_name} on {date}. "
        f"If you originally responded with UNSURE, please provide a YES or NO so this "
        f"coverage can be solidified. Thank you!"
    )
