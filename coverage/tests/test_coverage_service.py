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

    def test_no_skips_a_candidate_who_already_answered(self):
        # Simulate Carol already having a stale response on this request
        # (e.g. an admin nudged current_candidate around by hand) so that
        # when Bob declines, the cascade must skip straight past her to Dave.
        dave = make_employee("Dave", seniority_rank=4)
        ShiftResponse.objects.create(
            shift_request=self.sr, employee=self.carol, answer=ShiftResponse.Answer.NO
        )

        coverage_service.handle_response(self.bob_response, self.bob, "NO")
        self.sr.refresh_from_db()

        self.assertEqual(self.sr.current_candidate, dave)
        self.assertTrue(ShiftResponse.objects.filter(shift_request=self.sr, employee=dave).exists())

    def test_skipping_many_already_answered_candidates_does_not_add_queries(self):
        # _find_next_untried_candidate fetches the remaining roster and the
        # already-answered set in one query each, then walks them in Python
        # — so the number of already-declined candidates in front of the
        # real next one shouldn't change the query count. This is what
        # actually proves the O(k)-round-trips version is gone, rather than
        # just asserting on the end result (which the old, slower
        # implementation would also have gotten right).
        # Carol (from setUp, rank 3) also needs to be marked as already
        # answered, otherwise she — not "winner" — would be the correct
        # next candidate and the assertion below would be testing the
        # wrong thing.
        ShiftResponse.objects.create(shift_request=self.sr, employee=self.carol, answer=ShiftResponse.Answer.NO)
        candidates = [make_employee(f"Skip{i}", seniority_rank=10 + i) for i in range(15)]
        for c in candidates:
            ShiftResponse.objects.create(shift_request=self.sr, employee=c, answer=ShiftResponse.Answer.NO)
        winner = make_employee("Winner", seniority_rank=100)

        with self.assertNumQueries(2):
            next_candidate = coverage_service._find_next_untried_candidate(self.sr, self.bob)

        self.assertEqual(next_candidate, winner)

    def test_rejects_response_to_a_cancelled_request(self):
        # Bob's ask is still PENDING, but Alice cancelled the request out
        # from under him after it went out.
        coverage_service.cancel_request(self.sr, self.alice)
        with self.assertRaises(ValueError):
            coverage_service.handle_response(self.bob_response, self.bob, "YES")

        self.bob_response.refresh_from_db()
        self.assertEqual(self.bob_response.answer, ShiftResponse.Answer.PENDING)


class CancelRequestTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)

    def test_cancel_a_draft(self):
        sr = make_shift_request(self.alice, status=ShiftRequest.Status.DRAFT)
        coverage_service.cancel_request(sr, self.alice)
        sr.refresh_from_db()

        self.assertEqual(sr.status, ShiftRequest.Status.CANCELLED)
        event = CoverageEvent.objects.get(
            shift_request=sr, event_type=CoverageEvent.EventType.CANCELLED
        )
        self.assertIn("Alice", event.message)
        # No one was ever asked, so there's no one to notify.
        self.assertFalse(Notification.objects.filter(shift_request=sr).exists())

    def test_cancel_while_searching_notifies_current_candidate(self):
        sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(sr)

        coverage_service.cancel_request(sr, self.alice)
        sr.refresh_from_db()

        self.assertEqual(sr.status, ShiftRequest.Status.CANCELLED)
        self.assertIsNone(sr.current_candidate)
        self.assertTrue(
            Notification.objects.filter(
                employee=self.bob, shift_request=sr, message__icontains="cancelled"
            ).exists()
        )

    def test_cancelling_does_not_touch_the_pending_shift_response(self):
        # cancel_request doesn't mutate ShiftResponse rows — handle_response's
        # own status check is what prevents a stale Yes/No from being acted on.
        sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(sr)
        bob_response = ShiftResponse.objects.get(shift_request=sr, employee=self.bob)

        coverage_service.cancel_request(sr, self.alice)

        bob_response.refresh_from_db()
        self.assertEqual(bob_response.answer, ShiftResponse.Answer.PENDING)

    def test_cannot_cancel_a_covered_request(self):
        sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(sr)
        response = ShiftResponse.objects.get(shift_request=sr, employee=self.bob)
        coverage_service.handle_response(response, self.bob, "YES")
        sr.refresh_from_db()  # handle_response updated the DB row, not this local object

        with self.assertRaises(ValueError):
            coverage_service.cancel_request(sr, self.alice)

        sr.refresh_from_db()
        self.assertEqual(sr.status, ShiftRequest.Status.COVERED)

    def test_cannot_cancel_an_uncovered_request(self):
        sr = make_shift_request(self.bob)  # last in roster, so it exhausts immediately
        coverage_service.start_coverage_search(sr)

        with self.assertRaises(ValueError):
            coverage_service.cancel_request(sr, self.bob)

    def test_cannot_double_cancel(self):
        sr = make_shift_request(self.alice, status=ShiftRequest.Status.DRAFT)
        coverage_service.cancel_request(sr, self.alice)
        with self.assertRaises(ValueError):
            coverage_service.cancel_request(sr, self.alice)

    def test_only_the_requester_can_cancel(self):
        sr = make_shift_request(self.alice, status=ShiftRequest.Status.DRAFT)
        with self.assertRaises(ValueError):
            coverage_service.cancel_request(sr, self.bob)

        sr.refresh_from_db()
        self.assertEqual(sr.status, ShiftRequest.Status.DRAFT)
