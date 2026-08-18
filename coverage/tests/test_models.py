import datetime

from django.test import TestCase

from coverage import time_format
from coverage.models import CoverageEvent, Notification, ShiftRequest, ShiftResponse
from .factories import make_employee, make_shift_request


class EmployeeRosterTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)
        self.carol = make_employee("Carol", seniority_rank=3, is_active=False)
        self.dave = make_employee("Dave", seniority_rank=4)

    def test_get_next_in_roster_skips_inactive(self):
        self.assertEqual(self.alice.get_next_in_roster(), self.bob)
        # Carol (rank 3) is inactive, so Bob's next is Dave.
        self.assertEqual(self.bob.get_next_in_roster(), self.dave)

    def test_get_next_in_roster_returns_none_at_bottom(self):
        self.assertIsNone(self.dave.get_next_in_roster())


class ShiftRequestDisplayTests(TestCase):
    def test_display_helpers(self):
        requester = make_employee("Alice", seniority_rank=1)
        sr = ShiftRequest.objects.create(
            requester=requester,
            shift_date=datetime.date(2026, 8, 20),
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 30),
        )
        self.assertEqual(sr.day_display(), "Thursday")
        self.assertEqual(sr.date_display(), "August 20, 2026")
        self.assertEqual(sr.time_display(), "9:00 AM–5:30 PM")
        self.assertEqual(sr.status, ShiftRequest.Status.DRAFT)

    def test_time_display_honors_active_24h_preference(self):
        requester = make_employee("Alice", seniority_rank=1)
        sr = ShiftRequest.objects.create(
            requester=requester,
            shift_date=datetime.date(2026, 8, 20),
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 30),
        )
        time_format.activate(True)
        try:
            self.assertEqual(sr.time_display(), "09:00–17:30")
        finally:
            time_format.deactivate()

        self.assertEqual(sr.time_display(), "9:00 AM–5:30 PM")


class StrMethodTests(TestCase):
    """
    __str__ output backs the admin's list_display columns and log
    readability — a broken __str__ (e.g. a bad f-string) throws on every
    admin page load, so it's worth pinning.
    """

    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)
        self.sr = make_shift_request(self.alice)

    def test_employee_str(self):
        self.assertEqual(str(self.alice), "#1 Alice")

    def test_employee_get_phone_e164_with_no_number(self):
        self.assertEqual(self.alice.get_phone_e164(), "None")

    def test_shift_request_str(self):
        self.assertIn(f"ShiftRequest #{self.sr.pk}", str(self.sr))
        self.assertIn("Alice", str(self.sr))

    def test_shift_response_str(self):
        response = ShiftResponse.objects.create(shift_request=self.sr, employee=self.bob)
        self.assertIn("Bob", str(response))
        self.assertIn("PENDING", str(response))

    def test_coverage_event_str(self):
        event = CoverageEvent.objects.create(
            shift_request=self.sr, event_type=CoverageEvent.EventType.REQUEST_CREATED
        )
        self.assertIn("REQUEST_CREATED", str(event))
        self.assertIn(f"ShiftRequest #{self.sr.pk}", str(event))

    def test_notification_str(self):
        notification = Notification.objects.create(
            employee=self.bob, shift_request=self.sr, message="Hello there, this is a long message"
        )
        self.assertIn("Bob", str(notification))
        self.assertIn("Hello there, this is a", str(notification))
