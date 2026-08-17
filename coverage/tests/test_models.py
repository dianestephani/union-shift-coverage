import datetime

from django.test import TestCase

from coverage.models import ShiftRequest
from .factories import make_employee


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
