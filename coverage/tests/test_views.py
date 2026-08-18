import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from coverage import coverage_service
from coverage.models import Notification, ShiftRequest, ShiftResponse
from .factories import make_employee, make_shift_request

User = get_user_model()


class LoginGatingTests(TestCase):
    def setUp(self):
        self.employee = make_employee("Alice", seniority_rank=1)

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("login"))

    def test_authenticated_without_employee_redirected_to_login(self):
        orphan_user = User.objects.create_user(username="orphan", email="orphan@example.com")
        self.client.force_login(orphan_user)
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(response, reverse("login"))

    def test_authenticated_employee_sees_dashboard(self):
        self.client.force_login(self.employee.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)


class RosterViewTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)
        self.carol = make_employee("Carol", seniority_rank=3, is_active=False)

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(reverse("roster"))
        self.assertRedirects(response, reverse("login"))

    def test_any_logged_in_employee_sees_full_roster(self):
        self.client.force_login(self.bob.user)
        response = self.client.get(reverse("roster"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice")
        self.assertContains(response, "Bob")
        self.assertContains(response, "Carol")

    def test_roster_shows_inactive_status(self):
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("roster"))
        self.assertContains(response, "Inactive")


class DashboardPendingResponsesTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)
        self.sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(self.sr)

    def test_pending_candidate_sees_waiting_card(self):
        self.client.force_login(self.bob.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Requests waiting on you")
        self.assertContains(response, "Alice")

    def test_requester_does_not_see_waiting_card(self):
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "Requests waiting on you")


class RequesterCoverageVisibilityTests(TestCase):
    """The requester should always be able to see which of their shifts are
    up for coverage, who declined so far, and who's currently being asked."""

    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)
        self.carol = make_employee("Carol", seniority_rank=3)
        self.sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(self.sr)  # asks Bob first

    def test_dashboard_shows_who_is_currently_being_asked(self):
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Waiting on")
        self.assertContains(response, "Bob")

    def test_dashboard_updates_after_decline_cascades_to_next_candidate(self):
        bob_response = ShiftResponse.objects.get(shift_request=self.sr, employee=self.bob)
        coverage_service.handle_response(bob_response, self.bob, "NO")

        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Carol")

        self.sr.refresh_from_db()
        self.assertEqual(self.sr.current_candidate, self.carol)

    def test_detail_page_shows_current_candidate_and_declines(self):
        bob_response = ShiftResponse.objects.get(shift_request=self.sr, employee=self.bob)
        coverage_service.handle_response(bob_response, self.bob, "NO")

        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("shift_request_detail", args=[self.sr.pk]))

        # Bob declined
        self.assertContains(response, "Bob")
        self.assertContains(response, "No")
        # Carol is who we're waiting on now
        self.assertContains(response, "Waiting on")
        self.assertContains(response, "Carol")

    def test_draft_request_renders_without_error_and_has_no_candidate(self):
        # A DRAFT request has no current_candidate; the template must not
        # blow up trying to render `.name` on None for it.
        draft = make_shift_request(self.alice, shift_date=datetime.date(2026, 8, 27))
        self.assertIsNone(draft.current_candidate)

        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_stops_showing_candidate_once_covered(self):
        bob_response = ShiftResponse.objects.get(shift_request=self.sr, employee=self.bob)
        coverage_service.handle_response(bob_response, self.bob, "YES")

        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Covered")

        self.sr.refresh_from_db()
        self.assertIsNone(self.sr.current_candidate)

    def test_detail_page_hides_waiting_on_once_covered(self):
        bob_response = ShiftResponse.objects.get(shift_request=self.sr, employee=self.bob)
        coverage_service.handle_response(bob_response, self.bob, "YES")

        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("shift_request_detail", args=[self.sr.pk]))

        self.assertNotContains(response, "Waiting on")
        self.assertContains(response, "Covered by")

    def test_detail_page_hides_waiting_on_once_roster_exhausted(self):
        bob_response = ShiftResponse.objects.get(shift_request=self.sr, employee=self.bob)
        coverage_service.handle_response(bob_response, self.bob, "NO")
        carol_response = ShiftResponse.objects.get(shift_request=self.sr, employee=self.carol)
        coverage_service.handle_response(carol_response, self.carol, "NO")

        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("shift_request_detail", args=[self.sr.pk]))

        self.assertNotContains(response, "Waiting on")

        self.sr.refresh_from_db()
        self.assertEqual(self.sr.status, ShiftRequest.Status.UNCOVERED)
        self.assertIsNone(self.sr.current_candidate)


class RespondToShiftViewTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)
        self.carol = make_employee("Carol", seniority_rank=3)
        self.sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(self.sr)
        self.bob_response = ShiftResponse.objects.get(shift_request=self.sr, employee=self.bob)

    def test_requires_post(self):
        self.client.force_login(self.bob.user)
        url = reverse("respond_to_shift", args=[self.bob_response.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_owner_can_answer_yes(self):
        self.client.force_login(self.bob.user)
        url = reverse("respond_to_shift", args=[self.bob_response.pk])
        response = self.client.post(url, {"answer": "YES", "next": reverse("dashboard")})
        self.assertRedirects(response, reverse("dashboard"))

        self.bob_response.refresh_from_db()
        self.assertEqual(self.bob_response.answer, ShiftResponse.Answer.YES)

    def test_other_employee_gets_404(self):
        self.client.force_login(self.carol.user)
        url = reverse("respond_to_shift", args=[self.bob_response.pk])
        response = self.client.post(url, {"answer": "YES", "next": reverse("dashboard")})
        self.assertEqual(response.status_code, 404)

        self.bob_response.refresh_from_db()
        self.assertEqual(self.bob_response.answer, ShiftResponse.Answer.PENDING)

    def test_anonymous_redirected_to_login(self):
        url = reverse("respond_to_shift", args=[self.bob_response.pk])
        response = self.client.post(url, {"answer": "YES"})
        self.assertRedirects(response, reverse("login"))


class NotificationEndpointTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)
        self.sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(self.sr)
        self.notification = Notification.objects.get(employee=self.bob, shift_request=self.sr)

    def test_poll_returns_unread_notifications_for_logged_in_employee(self):
        self.client.force_login(self.bob.user)
        response = self.client.get(reverse("notifications_poll"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["unread_count"], 1)
        self.assertEqual(data["notifications"][0]["id"], self.notification.pk)

    def test_poll_does_not_leak_other_employees_notifications(self):
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("notifications_poll"))
        data = response.json()
        self.assertEqual(data["unread_count"], 0)

    def test_mark_read(self):
        self.client.force_login(self.bob.user)
        url = reverse("notification_mark_read", args=[self.notification.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)

        self.notification.refresh_from_db()
        self.assertIsNotNone(self.notification.read_at)

    def test_cannot_mark_another_employees_notification_read(self):
        self.client.force_login(self.alice.user)
        url = reverse("notification_mark_read", args=[self.notification.pk])
        self.client.post(url)

        self.notification.refresh_from_db()
        self.assertIsNone(self.notification.read_at)


class ShiftRequestFlowTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)

    def test_form_describes_in_app_notification_not_texting(self):
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("shift_request_new"))
        self.assertContains(response, "notify the roster in-app")
        self.assertNotContains(response, "texting")

    def test_save_draft_does_not_start_search(self):
        self.client.force_login(self.alice.user)
        response = self.client.post(reverse("shift_request_new"), {
            "shift_date": "2026-08-20",
            "start_time": "09:00",
            "end_time": "17:00",
            "notes": "",
            "action": "save_draft",
        })
        self.assertRedirects(response, reverse("dashboard"))
        sr = ShiftRequest.objects.get(requester=self.alice)
        self.assertEqual(sr.status, ShiftRequest.Status.DRAFT)

    def test_find_coverage_starts_search(self):
        self.client.force_login(self.alice.user)
        response = self.client.post(reverse("shift_request_new"), {
            "shift_date": "2026-08-20",
            "start_time": "09:00",
            "end_time": "17:00",
            "notes": "",
            "action": "find_coverage",
        })
        self.assertRedirects(response, reverse("dashboard"))
        sr = ShiftRequest.objects.get(requester=self.alice)
        self.assertEqual(sr.status, ShiftRequest.Status.SEARCHING)
        self.assertEqual(sr.current_candidate, self.bob)

    def test_detail_view_scoped_to_requester(self):
        sr = make_shift_request(self.alice)
        self.client.force_login(self.bob.user)
        response = self.client.get(reverse("shift_request_detail", args=[sr.pk]))
        self.assertEqual(response.status_code, 404)
