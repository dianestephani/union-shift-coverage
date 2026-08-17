from django.test import TestCase

from coverage import coverage_service
from coverage.models import CoverageEvent, Notification, ShiftRequest, ShiftResponse
from .factories import make_employee, make_shift_request


class StartCoverageSearchTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)

    def test_activates_and_asks_next_candidate(self):
        sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(sr)
        sr.refresh_from_db()

        self.assertEqual(sr.status, ShiftRequest.Status.SEARCHING)
        self.assertEqual(sr.current_candidate, self.bob)

        response = ShiftResponse.objects.get(shift_request=sr, employee=self.bob)
        self.assertEqual(response.answer, ShiftResponse.Answer.PENDING)

        notification = Notification.objects.get(employee=self.bob, shift_request=sr)
        self.assertEqual(notification.action_response, response)
        self.assertIn("Alice", notification.message)

        self.assertTrue(
            CoverageEvent.objects.filter(
                shift_request=sr, event_type=CoverageEvent.EventType.REQUEST_ACTIVATED
            ).exists()
        )

    def test_raises_if_not_draft(self):
        sr = make_shift_request(self.alice, status=ShiftRequest.Status.SEARCHING)
        with self.assertRaises(ValueError):
            coverage_service.start_coverage_search(sr)

    def test_no_one_below_requester_marks_uncovered(self):
        # Bob is last in the roster, so there's nobody left to ask.
        sr = make_shift_request(self.bob)
        coverage_service.start_coverage_search(sr)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ShiftRequest.Status.UNCOVERED)


class HandleResponseTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)
        self.carol = make_employee("Carol", seniority_rank=3)
        self.sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(self.sr)
        self.bob_response = ShiftResponse.objects.get(shift_request=self.sr, employee=self.bob)

    def test_yes_covers_shift_and_notifies_both_parties(self):
        coverage_service.handle_response(self.bob_response, self.bob, "YES")
        self.sr.refresh_from_db()

        self.assertEqual(self.sr.status, ShiftRequest.Status.COVERED)
        self.assertEqual(self.sr.covered_by, self.bob)
        self.assertIsNone(self.sr.current_candidate)

        self.bob_response.refresh_from_db()
        self.assertEqual(self.bob_response.answer, ShiftResponse.Answer.YES)
        self.assertIsNotNone(self.bob_response.answered_at)

        self.assertTrue(Notification.objects.filter(employee=self.bob, shift_request=self.sr).exists())
        self.assertTrue(Notification.objects.filter(employee=self.alice, shift_request=self.sr).exists())

        self.assertTrue(
            CoverageEvent.objects.filter(
                shift_request=self.sr, event_type=CoverageEvent.EventType.COVERED
            ).exists()
        )

    def test_no_advances_to_next_candidate(self):
        coverage_service.handle_response(self.bob_response, self.bob, "NO")
        self.sr.refresh_from_db()

        self.assertEqual(self.sr.status, ShiftRequest.Status.SEARCHING)
        self.assertEqual(self.sr.current_candidate, self.carol)
        self.assertTrue(ShiftResponse.objects.filter(shift_request=self.sr, employee=self.carol).exists())

        # Requester gets a decline notification.
        self.assertTrue(
            Notification.objects.filter(
                employee=self.alice, shift_request=self.sr, message__icontains="declined"
            ).exists()
        )

    def test_no_from_last_candidate_marks_uncovered(self):
        coverage_service.handle_response(self.bob_response, self.bob, "NO")
        carol_response = ShiftResponse.objects.get(shift_request=self.sr, employee=self.carol)

        coverage_service.handle_response(carol_response, self.carol, "NO")
        self.sr.refresh_from_db()

        self.assertEqual(self.sr.status, ShiftRequest.Status.UNCOVERED)
        self.assertIsNone(self.sr.current_candidate)

    def test_rejects_answer_from_wrong_employee(self):
        with self.assertRaises(ValueError):
            coverage_service.handle_response(self.bob_response, self.alice, "YES")

    def test_rejects_already_answered_response(self):
        coverage_service.handle_response(self.bob_response, self.bob, "YES")
        with self.assertRaises(ValueError):
            coverage_service.handle_response(self.bob_response, self.bob, "NO")

    def test_rejects_invalid_answer_value(self):
        with self.assertRaises(ValueError):
            coverage_service.handle_response(self.bob_response, self.bob, "MAYBE")
