import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from coverage import coverage_service
from coverage.models import Notification, ShiftRequest, ShiftResponse
from coverage.notifications import prune_notifications
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


class NavigationTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)

    def test_logged_in_nav_has_dashboard_link(self):
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("roster"))
        self.assertContains(response, ">Dashboard<")
        self.assertContains(response, reverse("dashboard"))

    def test_logged_out_nav_has_no_dashboard_link(self):
        response = self.client.get(reverse("login"))
        self.assertNotContains(response, ">Dashboard<")


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

    def test_roster_shows_email_and_phone(self):
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("roster"))
        self.assertContains(response, "alice@example.com")
        self.assertContains(response, "bob@example.com")

    def test_roster_shows_placeholder_for_missing_phone(self):
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("roster"))
        self.assertContains(response, "—")


class SettingsViewTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(reverse("settings"))
        self.assertRedirects(response, reverse("login"))

    def test_get_shows_current_timezone(self):
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "America/Chicago")

    def test_post_updates_own_timezone(self):
        self.client.force_login(self.alice.user)
        response = self.client.post(reverse("settings"), {"timezone": "Asia/Tokyo"})
        self.assertRedirects(response, reverse("settings"))

        self.alice.refresh_from_db()
        self.assertEqual(self.alice.timezone, "Asia/Tokyo")

    def test_post_does_not_affect_other_employees(self):
        self.client.force_login(self.alice.user)
        self.client.post(reverse("settings"), {"timezone": "Asia/Tokyo"})

        self.bob.refresh_from_db()
        self.assertEqual(self.bob.timezone, "America/Chicago")

    def test_invalid_timezone_choice_is_rejected(self):
        self.client.force_login(self.alice.user)
        response = self.client.post(reverse("settings"), {"timezone": "Mars/Olympus_Mons"})
        self.assertEqual(response.status_code, 200)
        self.alice.refresh_from_db()
        self.assertEqual(self.alice.timezone, "America/Chicago")

    def test_military_time_defaults_to_off(self):
        self.assertFalse(self.alice.military_time)

    def test_post_enables_military_time(self):
        self.client.force_login(self.alice.user)
        # Checkboxes only appear in POST data when checked.
        response = self.client.post(
            reverse("settings"), {"timezone": "America/Chicago", "military_time": "on"}
        )
        self.assertRedirects(response, reverse("settings"))
        self.alice.refresh_from_db()
        self.assertTrue(self.alice.military_time)

    def test_omitting_military_time_from_post_turns_it_off(self):
        self.alice.military_time = True
        self.alice.save(update_fields=["military_time"])

        self.client.force_login(self.alice.user)
        self.client.post(reverse("settings"), {"timezone": "America/Chicago"})

        self.alice.refresh_from_db()
        self.assertFalse(self.alice.military_time)


class EmployeeTimezoneMiddlewareTests(TestCase):
    """
    Testing this by scraping rendered timestamps out of HTML is fragile
    (Django's default datetime formatting, day-boundary edge cases, and the
    24h notification-retention window all get in the way). Instead, check
    directly what timezone the middleware activated for the request —
    that's the actual behavior this middleware is responsible for.
    """

    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)

    def test_activates_employees_chosen_timezone(self):
        self.alice.timezone = "Asia/Tokyo"
        self.alice.save(update_fields=["timezone"])
        self.client.force_login(self.alice.user)

        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(timezone.get_current_timezone()), "Asia/Tokyo")

    def test_defaults_to_employees_default_timezone(self):
        self.client.force_login(self.alice.user)
        self.client.get(reverse("dashboard"))
        self.assertEqual(str(timezone.get_current_timezone()), "America/Chicago")

    def test_dashboard_shows_12h_time_by_default(self):
        make_shift_request(self.alice, start_time=datetime.time(14, 0), end_time=datetime.time(22, 0))
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "2:00 PM–10:00 PM")

    def test_dashboard_shows_24h_time_when_employee_prefers_it(self):
        self.alice.military_time = True
        self.alice.save(update_fields=["military_time"])
        make_shift_request(self.alice, start_time=datetime.time(14, 0), end_time=datetime.time(22, 0))

        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "14:00–22:00")

    def test_falls_back_to_server_timezone_when_logged_out(self):
        from django.conf import settings

        self.client.get(reverse("login"))
        self.assertEqual(str(timezone.get_current_timezone()), settings.TIME_ZONE)


class DashboardPendingResponsesTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)
        self.sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(self.sr)

    def test_pending_candidate_sees_waiting_card(self):
        self.client.force_login(self.bob.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Waiting on you")
        self.assertContains(response, "Alice")

    def test_requester_sees_empty_waiting_list(self):
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Nothing waiting on you.")


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

    def test_next_pointing_off_site_is_ignored(self):
        # `next` is a plain POST field, not a signed/trusted value — an
        # attacker-crafted form could set it to an external URL to use this
        # site as an open-redirect stepping stone to a phishing page.
        self.client.force_login(self.bob.user)
        url = reverse("respond_to_shift", args=[self.bob_response.pk])
        response = self.client.post(url, {"answer": "YES", "next": "https://evil.example.com/phish"})
        self.assertRedirects(response, reverse("dashboard"))

    def test_protocol_relative_next_is_ignored(self):
        self.client.force_login(self.bob.user)
        url = reverse("respond_to_shift", args=[self.bob_response.pk])
        response = self.client.post(url, {"answer": "YES", "next": "//evil.example.com/phish"})
        self.assertRedirects(response, reverse("dashboard"))

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

    def test_ajax_request_returns_json_instead_of_redirect(self):
        self.client.force_login(self.bob.user)
        url = reverse("respond_to_shift", args=[self.bob_response.pk])
        response = self.client.post(
            url, {"answer": "YES"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})

        self.bob_response.refresh_from_db()
        self.assertEqual(self.bob_response.answer, ShiftResponse.Answer.YES)

    def test_ajax_request_returns_json_error_for_invalid_answer(self):
        self.client.force_login(self.bob.user)
        url = reverse("respond_to_shift", args=[self.bob_response.pk])
        response = self.client.post(
            url, {"answer": "MAYBE"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

        self.bob_response.refresh_from_db()
        self.assertEqual(self.bob_response.answer, ShiftResponse.Answer.PENDING)

    def test_non_ajax_invalid_answer_shows_error_message_and_redirects(self):
        self.client.force_login(self.bob.user)
        url = reverse("respond_to_shift", args=[self.bob_response.pk])
        response = self.client.post(url, {"answer": "MAYBE"}, follow=True)

        self.assertRedirects(response, reverse("dashboard"))
        messages = list(response.context["messages"])
        self.assertTrue(any("Unrecognised answer" in str(m) for m in messages))

        self.bob_response.refresh_from_db()
        self.assertEqual(self.bob_response.answer, ShiftResponse.Answer.PENDING)

    def test_non_ajax_double_submit_shows_already_answered_error(self):
        self.client.force_login(self.bob.user)
        url = reverse("respond_to_shift", args=[self.bob_response.pk])
        self.client.post(url, {"answer": "YES"})

        response = self.client.post(url, {"answer": "NO"}, follow=True)
        messages = list(response.context["messages"])
        self.assertTrue(any("already been answered" in str(m) for m in messages))

        self.bob_response.refresh_from_db()
        self.assertEqual(self.bob_response.answer, ShiftResponse.Answer.YES)

    def test_missing_answer_field_is_treated_as_invalid(self):
        self.client.force_login(self.bob.user)
        url = reverse("respond_to_shift", args=[self.bob_response.pk])
        response = self.client.post(url, {}, follow=True)

        messages = list(response.context["messages"])
        self.assertTrue(any("Unrecognised answer" in str(m) for m in messages))

        self.bob_response.refresh_from_db()
        self.assertEqual(self.bob_response.answer, ShiftResponse.Answer.PENDING)


class ShiftRequestActivateViewTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)
        self.sr = make_shift_request(self.alice, status=ShiftRequest.Status.DRAFT)

    def test_owner_can_activate_a_draft(self):
        self.client.force_login(self.alice.user)
        url = reverse("shift_request_activate", args=[self.sr.pk])
        response = self.client.post(url)

        self.assertRedirects(response, reverse("shift_request_detail", args=[self.sr.pk]))
        self.sr.refresh_from_db()
        self.assertEqual(self.sr.status, ShiftRequest.Status.SEARCHING)
        self.assertEqual(self.sr.current_candidate, self.bob)

    def test_get_request_does_not_activate(self):
        self.client.force_login(self.alice.user)
        url = reverse("shift_request_activate", args=[self.sr.pk])
        response = self.client.get(url)

        self.assertRedirects(response, reverse("shift_request_detail", args=[self.sr.pk]))
        self.sr.refresh_from_db()
        self.assertEqual(self.sr.status, ShiftRequest.Status.DRAFT)

    def test_non_draft_request_404s(self):
        self.sr.status = ShiftRequest.Status.SEARCHING
        self.sr.save(update_fields=["status"])

        self.client.force_login(self.alice.user)
        url = reverse("shift_request_activate", args=[self.sr.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_non_owner_gets_404(self):
        self.client.force_login(self.bob.user)
        url = reverse("shift_request_activate", args=[self.sr.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_manager_still_cannot_activate_someone_elses_draft(self):
        # Managers can *view* every request (see shift_request_detail), but
        # starting a coverage search is the requester's own call to make —
        # that elevated access shouldn't extend to taking actions for them.
        manager = make_employee("Manny", seniority_rank=3, is_manager=True)
        self.client.force_login(manager.user)
        url = reverse("shift_request_activate", args=[self.sr.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

        self.sr.refresh_from_db()
        self.assertEqual(self.sr.status, ShiftRequest.Status.DRAFT)

    def test_anonymous_user_redirected_to_login(self):
        url = reverse("shift_request_activate", args=[self.sr.pk])
        response = self.client.post(url)
        self.assertRedirects(response, reverse("login"))


class ShiftRequestCancelViewTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)

    def test_owner_can_cancel_a_draft(self):
        sr = make_shift_request(self.alice, status=ShiftRequest.Status.DRAFT)
        self.client.force_login(self.alice.user)
        response = self.client.post(reverse("shift_request_cancel", args=[sr.pk]))

        self.assertRedirects(response, reverse("shift_request_detail", args=[sr.pk]))
        sr.refresh_from_db()
        self.assertEqual(sr.status, ShiftRequest.Status.CANCELLED)

    def test_owner_can_cancel_a_searching_request(self):
        sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(sr)
        self.client.force_login(self.alice.user)
        response = self.client.post(reverse("shift_request_cancel", args=[sr.pk]))

        self.assertRedirects(response, reverse("shift_request_detail", args=[sr.pk]))
        sr.refresh_from_db()
        self.assertEqual(sr.status, ShiftRequest.Status.CANCELLED)

    def test_get_request_does_not_cancel(self):
        sr = make_shift_request(self.alice, status=ShiftRequest.Status.DRAFT)
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("shift_request_cancel", args=[sr.pk]))

        self.assertEqual(response.status_code, 405)
        sr.refresh_from_db()
        self.assertEqual(sr.status, ShiftRequest.Status.DRAFT)

    def test_non_owner_gets_404(self):
        sr = make_shift_request(self.alice, status=ShiftRequest.Status.DRAFT)
        self.client.force_login(self.bob.user)
        response = self.client.post(reverse("shift_request_cancel", args=[sr.pk]))
        self.assertEqual(response.status_code, 404)

    def test_manager_cannot_cancel_someone_elses_request(self):
        manager = make_employee("Manny", seniority_rank=3, is_manager=True)
        sr = make_shift_request(self.alice, status=ShiftRequest.Status.DRAFT)
        self.client.force_login(manager.user)
        response = self.client.post(reverse("shift_request_cancel", args=[sr.pk]))
        self.assertEqual(response.status_code, 404)

        sr.refresh_from_db()
        self.assertEqual(sr.status, ShiftRequest.Status.DRAFT)

    def test_cancelling_an_already_covered_request_shows_error(self):
        sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(sr)
        response = ShiftResponse.objects.get(shift_request=sr, employee=self.bob)
        coverage_service.handle_response(response, self.bob, "YES")

        self.client.force_login(self.alice.user)
        result = self.client.post(reverse("shift_request_cancel", args=[sr.pk]), follow=True)

        messages = list(result.context["messages"])
        self.assertTrue(any("already" in str(m).lower() or "covered" in str(m).lower() for m in messages))
        sr.refresh_from_db()
        self.assertEqual(sr.status, ShiftRequest.Status.COVERED)

    def test_anonymous_user_redirected_to_login(self):
        sr = make_shift_request(self.alice, status=ShiftRequest.Status.DRAFT)
        response = self.client.post(reverse("shift_request_cancel", args=[sr.pk]))
        self.assertRedirects(response, reverse("login"))

    def test_cancelled_request_no_longer_shows_on_candidates_waiting_list(self):
        sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(sr)

        self.client.force_login(self.alice.user)
        self.client.post(reverse("shift_request_cancel", args=[sr.pk]))

        self.client.force_login(self.bob.user)
        dashboard = self.client.get(reverse("dashboard"))
        self.assertNotIn(
            ShiftResponse.objects.get(shift_request=sr, employee=self.bob),
            list(dashboard.context["my_pending_responses"]),
        )

    def test_cancel_button_shown_on_draft_and_searching(self):
        self.client.force_login(self.alice.user)

        draft = make_shift_request(self.alice, status=ShiftRequest.Status.DRAFT)
        response = self.client.get(reverse("shift_request_detail", args=[draft.pk]))
        self.assertContains(response, "Cancel request")

        searching = make_shift_request(self.alice)
        coverage_service.start_coverage_search(searching)
        response = self.client.get(reverse("shift_request_detail", args=[searching.pk]))
        self.assertContains(response, "Cancel request")

    def test_cancel_button_hidden_on_resolved_requests(self):
        self.client.force_login(self.alice.user)

        covered = make_shift_request(self.alice)
        coverage_service.start_coverage_search(covered)
        response = ShiftResponse.objects.get(shift_request=covered, employee=self.bob)
        coverage_service.handle_response(response, self.bob, "YES")
        page = self.client.get(reverse("shift_request_detail", args=[covered.pk]))
        self.assertNotContains(page, "Cancel request")

        cancelled = make_shift_request(self.alice, status=ShiftRequest.Status.DRAFT)
        coverage_service.cancel_request(cancelled, self.alice)
        page = self.client.get(reverse("shift_request_detail", args=[cancelled.pk]))
        self.assertNotContains(page, "Cancel request")

    def test_cancelled_request_notification_no_longer_offers_answer_buttons(self):
        sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(sr)

        self.client.force_login(self.alice.user)
        self.client.post(reverse("shift_request_cancel", args=[sr.pk]))

        self.client.force_login(self.bob.user)
        data = self.client.get(reverse("notifications_poll")).json()
        matching = [n for n in data["notifications"] if n["shift_request_id"] == sr.pk]
        self.assertTrue(matching)
        self.assertIsNone(matching[0]["action_response_id"])


class MyCoverageListsTests(TestCase):
    """Every employee should see their own waiting / covering / declined
    shifts on the dashboard, regardless of who requested them."""

    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)
        self.carol = make_employee("Carol", seniority_rank=3)

        self.covering_sr = make_shift_request(self.alice, shift_date=datetime.date(2026, 8, 21))
        coverage_service.start_coverage_search(self.covering_sr)
        bob_covering_response = ShiftResponse.objects.get(
            shift_request=self.covering_sr, employee=self.bob
        )
        coverage_service.handle_response(bob_covering_response, self.bob, "YES")

        self.declined_sr = make_shift_request(self.alice, shift_date=datetime.date(2026, 8, 22))
        coverage_service.start_coverage_search(self.declined_sr)
        bob_declined_response = ShiftResponse.objects.get(
            shift_request=self.declined_sr, employee=self.bob
        )
        coverage_service.handle_response(bob_declined_response, self.bob, "NO")

        self.waiting_sr = make_shift_request(self.alice, shift_date=datetime.date(2026, 8, 23))
        coverage_service.start_coverage_search(self.waiting_sr)  # Bob asked, left pending

    def test_dashboard_shows_all_three_lists_for_bob(self):
        self.client.force_login(self.bob.user)
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "You're covering")
        self.assertContains(response, "You declined")
        self.assertContains(response, "Waiting on you")

        pending = list(response.context["my_pending_responses"])
        covering = list(response.context["my_covering"])
        declined = list(response.context["my_declined"])

        self.assertEqual([r.shift_request for r in pending], [self.waiting_sr])
        self.assertEqual([r.shift_request for r in covering], [self.covering_sr])
        self.assertEqual([r.shift_request for r in declined], [self.declined_sr])

    def test_lists_are_scoped_to_the_logged_in_employee(self):
        self.client.force_login(self.carol.user)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(list(response.context["my_covering"]), [])
        self.assertEqual(list(response.context["my_declined"]), [])


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

    def test_mark_read_redirects_to_next_when_provided(self):
        self.client.force_login(self.bob.user)
        url = reverse("notification_mark_read", args=[self.notification.pk])
        response = self.client.post(url, {"next": reverse("notifications_page")})
        self.assertRedirects(response, reverse("notifications_page"))

        self.notification.refresh_from_db()
        self.assertIsNotNone(self.notification.read_at)

    def test_mark_read_ignores_off_site_next(self):
        self.client.force_login(self.bob.user)
        url = reverse("notification_mark_read", args=[self.notification.pk])
        response = self.client.post(url, {"next": "//evil.example.com/phish"})
        self.assertRedirects(response, reverse("dashboard"))

    def test_marking_an_already_read_notification_again_is_a_noop(self):
        self.client.force_login(self.bob.user)
        url = reverse("notification_mark_read", args=[self.notification.pk])
        self.client.post(url)
        self.notification.refresh_from_db()
        first_read_at = self.notification.read_at

        self.client.post(url)
        self.notification.refresh_from_db()
        self.assertEqual(self.notification.read_at, first_read_at)

    def test_answering_marks_its_notification_read_without_a_client_followup(self):
        # The client is expected to call notification_mark_read after a
        # successful answer, but the server must not depend on that
        # follow-up actually happening (dropped request, direct API call,
        # etc.) — otherwise the notification is stuck advertising buttons
        # for a response that's no longer PENDING.
        self.client.force_login(self.bob.user)
        response = ShiftResponse.objects.get(shift_request=self.sr, employee=self.bob)
        url = reverse("respond_to_shift", args=[response.pk])
        self.client.post(url, {"answer": "YES"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.notification.refresh_from_db()
        self.assertIsNotNone(self.notification.read_at)

    def test_poll_never_advertises_buttons_for_an_already_answered_response(self):
        response = ShiftResponse.objects.get(shift_request=self.sr, employee=self.bob)
        coverage_service.handle_response(response, self.bob, "YES")

        # Simulate the notification staying unread (e.g. the client-side
        # mark-read call never fired) — poll must still refuse to offer
        # Accept/Decline for it.
        Notification.objects.filter(pk=self.notification.pk).update(read_at=None)

        self.client.force_login(self.bob.user)
        data = self.client.get(reverse("notifications_poll")).json()
        matching = [n for n in data["notifications"] if n["id"] == self.notification.pk]
        self.assertEqual(len(matching), 1)
        self.assertIsNone(matching[0]["action_response_id"])

    def test_declining_also_marks_its_notification_read(self):
        # Mirrors the YES-path test above — the NO path cascades to the
        # next candidate via different code (_handle_no), so it's worth
        # confirming the mark-read fix isn't specific to acceptance.
        self.client.force_login(self.bob.user)
        response = ShiftResponse.objects.get(shift_request=self.sr, employee=self.bob)
        url = reverse("respond_to_shift", args=[response.pk])
        self.client.post(url, {"answer": "NO"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.notification.refresh_from_db()
        self.assertIsNotNone(self.notification.read_at)

    def test_answering_does_not_mark_unrelated_notifications_read(self):
        # A second, unrelated ask for Bob should be untouched by him
        # answering the first one.
        other_sr = make_shift_request(self.alice, shift_date=datetime.date(2026, 9, 1))
        coverage_service.start_coverage_search(other_sr)
        other_notification = Notification.objects.get(
            employee=self.bob, shift_request=other_sr
        )

        self.client.force_login(self.bob.user)
        response = ShiftResponse.objects.get(shift_request=self.sr, employee=self.bob)
        url = reverse("respond_to_shift", args=[response.pk])
        self.client.post(url, {"answer": "YES"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        other_notification.refresh_from_db()
        self.assertIsNone(other_notification.read_at)

        # The one actually tied to the answered response should be read.
        self.notification.refresh_from_db()
        self.assertIsNotNone(self.notification.read_at)


class NotificationsPageTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)
        self.sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(self.sr)
        self.notification = Notification.objects.get(employee=self.bob, shift_request=self.sr)

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(reverse("notifications_page"))
        self.assertRedirects(response, reverse("login"))

    def test_lists_notifications_for_logged_in_employee(self):
        self.client.force_login(self.bob.user)
        response = self.client.get(reverse("notifications_page"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "is looking for shift coverage")

    def test_does_not_leak_other_employees_notifications(self):
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("notifications_page"))
        self.assertNotContains(response, "is looking for shift coverage")


class NotificationRetentionTests(TestCase):
    def setUp(self):
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)
        self.sr = make_shift_request(self.alice)

    def test_notifications_older_than_24h_are_pruned(self):
        from coverage.notifications import notify

        old = notify(self.bob, self.sr, "old notification")
        Notification.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - datetime.timedelta(hours=25)
        )

        self.client.force_login(self.bob.user)
        response = self.client.get(reverse("notifications_page"))

        self.assertFalse(Notification.objects.filter(pk=old.pk).exists())
        self.assertNotContains(response, "old notification")

    def test_only_10_most_recent_notifications_are_kept(self):
        from coverage.notifications import notify

        for i in range(12):
            notify(self.bob, self.sr, f"notification {i}")

        self.assertEqual(Notification.objects.filter(employee=self.bob).count(), 10)
        remaining_messages = set(
            Notification.objects.filter(employee=self.bob).values_list("message", flat=True)
        )
        self.assertEqual(
            remaining_messages,
            {f"notification {i}" for i in range(2, 12)},
        )

    def test_pending_actionable_notification_survives_the_cap(self):
        # If Bob still owes a Yes/No on a coverage request, that notification
        # must not get pushed out by a flood of unrelated ones — otherwise
        # he'd stop seeing the "can you cover this?" prompt in his bell/
        # notifications page even though the request is still waiting on him.
        from coverage.notifications import notify

        coverage_service.start_coverage_search(self.sr)
        actionable = Notification.objects.get(
            employee=self.bob, shift_request=self.sr, action_response__isnull=False
        )

        for i in range(15):
            notify(self.bob, self.sr, f"unrelated fyi {i}")

        self.assertTrue(Notification.objects.filter(pk=actionable.pk).exists())

    def test_pending_actionable_notification_survives_expiry(self):
        coverage_service.start_coverage_search(self.sr)
        actionable = Notification.objects.get(
            employee=self.bob, shift_request=self.sr, action_response__isnull=False
        )
        Notification.objects.filter(pk=actionable.pk).update(
            created_at=timezone.now() - datetime.timedelta(hours=25)
        )

        prune_notifications(self.bob)

        self.assertTrue(Notification.objects.filter(pk=actionable.pk).exists())

    def test_answered_notification_is_no_longer_exempt_from_the_cap(self):
        # Once Bob actually answers, the notification isn't "actionable"
        # anymore and should go back to being subject to normal pruning.
        from coverage.notifications import notify

        coverage_service.start_coverage_search(self.sr)
        response = ShiftResponse.objects.get(shift_request=self.sr, employee=self.bob)
        coverage_service.handle_response(response, self.bob, "YES")
        answered = Notification.objects.get(
            employee=self.bob, shift_request=self.sr, action_response=response
        )

        for i in range(15):
            notify(self.bob, self.sr, f"unrelated fyi {i}")

        self.assertFalse(Notification.objects.filter(pk=answered.pk).exists())


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

    def test_manager_can_view_anyone_elses_request(self):
        manager = make_employee("Manny", seniority_rank=3, is_manager=True)
        sr = make_shift_request(self.alice)
        self.client.force_login(manager.user)
        response = self.client.get(reverse("shift_request_detail", args=[sr.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice")

    def test_invalid_post_rerenders_form_with_errors(self):
        self.client.force_login(self.alice.user)
        response = self.client.post(reverse("shift_request_new"), {
            "shift_date": "",
            "start_time": "09:00",
            "end_time": "17:00",
            "notes": "",
            "action": "save_draft",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].errors)
        self.assertFalse(ShiftRequest.objects.filter(requester=self.alice).exists())


class ManagerDashboardTests(TestCase):
    def setUp(self):
        self.manager = make_employee("Manny", seniority_rank=1, is_manager=True)
        self.alice = make_employee("Alice", seniority_rank=2)
        self.bob = make_employee("Bob", seniority_rank=3)

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(reverse("manager_dashboard"))
        self.assertRedirects(response, reverse("login"))

    def test_non_manager_gets_404(self):
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("manager_dashboard"))
        self.assertEqual(response.status_code, 404)

    def test_manager_sees_the_page(self):
        self.client.force_login(self.manager.user)
        response = self.client.get(reverse("manager_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice")
        self.assertContains(response, "Bob")

    def test_shows_draft_and_searching_requests_as_open(self):
        draft = make_shift_request(self.bob, status=ShiftRequest.Status.DRAFT)
        # Alice (rank 2) has Bob (rank 3) below her, so this one stays SEARCHING.
        searching = make_shift_request(self.alice)
        coverage_service.start_coverage_search(searching)

        self.client.force_login(self.manager.user)
        response = self.client.get(reverse("manager_dashboard"))
        open_requests = list(response.context["open_requests"])
        self.assertIn(draft, open_requests)
        self.assertIn(searching, open_requests)

    def test_covered_and_uncovered_requests_are_not_open(self):
        # Alice (rank 2) requests, Bob (rank 3, last in roster) responds.
        covered = make_shift_request(self.alice)
        coverage_service.start_coverage_search(covered)
        response = ShiftResponse.objects.get(shift_request=covered, employee=self.bob)
        coverage_service.handle_response(response, self.bob, "YES")

        uncovered = make_shift_request(self.alice, shift_date=datetime.date(2026, 9, 1))
        coverage_service.start_coverage_search(uncovered)
        response2 = ShiftResponse.objects.get(shift_request=uncovered, employee=self.bob)
        coverage_service.handle_response(response2, self.bob, "NO")

        self.client.force_login(self.manager.user)
        response = self.client.get(reverse("manager_dashboard"))
        open_requests = list(response.context["open_requests"])
        self.assertNotIn(covered, open_requests)
        self.assertNotIn(uncovered, open_requests)

    def test_shows_recent_activity(self):
        sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(sr)

        self.client.force_login(self.manager.user)
        response = self.client.get(reverse("manager_dashboard"))
        self.assertContains(response, "Coverage search started")

    def test_manager_link_visible_in_nav_only_for_managers(self):
        self.client.force_login(self.manager.user)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, reverse("manager_dashboard"))

        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, reverse("manager_dashboard"))


class ManagerEmployeeDetailTests(TestCase):
    def setUp(self):
        self.manager = make_employee("Manny", seniority_rank=1, is_manager=True)
        self.alice = make_employee("Alice", seniority_rank=2)
        self.bob = make_employee("Bob", seniority_rank=3)

    def test_anonymous_user_redirected_to_login(self):
        response = self.client.get(reverse("manager_employee_detail", args=[self.alice.pk]))
        self.assertRedirects(response, reverse("login"))

    def test_non_manager_gets_404(self):
        self.client.force_login(self.alice.user)
        response = self.client.get(reverse("manager_employee_detail", args=[self.bob.pk]))
        self.assertEqual(response.status_code, 404)

    def test_manager_sees_employees_request_and_response_history(self):
        sr = make_shift_request(self.alice)
        coverage_service.start_coverage_search(sr)

        self.client.force_login(self.manager.user)

        alice_page = self.client.get(reverse("manager_employee_detail", args=[self.alice.pk]))
        self.assertEqual(alice_page.status_code, 200)
        self.assertIn(sr, list(alice_page.context["requests"]))

        bob_page = self.client.get(reverse("manager_employee_detail", args=[self.bob.pk]))
        bob_response = ShiftResponse.objects.get(shift_request=sr, employee=self.bob)
        self.assertIn(bob_response, list(bob_page.context["responses"]))

    def test_unknown_employee_404s(self):
        self.client.force_login(self.manager.user)
        response = self.client.get(reverse("manager_employee_detail", args=[99999]))
        self.assertEqual(response.status_code, 404)

    def test_shows_profile_fields(self):
        self.client.force_login(self.manager.user)
        response = self.client.get(reverse("manager_employee_detail", args=[self.alice.pk]))
        self.assertContains(response, "Alice")
        self.assertContains(response, "alice@example.com")
        self.assertContains(response, "#2")  # seniority rank
        self.assertContains(response, "Central Time")  # get_timezone_display default

    def test_shows_empty_states_for_employee_with_no_history(self):
        self.client.force_login(self.manager.user)
        response = self.client.get(reverse("manager_employee_detail", args=[self.alice.pk]))
        self.assertContains(response, "hasn't requested any coverage")
        self.assertContains(response, "hasn't been asked to cover anything")

    def test_hides_find_coverage_button_on_someone_elses_request(self):
        # A manager viewing Alice's draft via the shared detail page
        # shouldn't be offered a button to activate it on her behalf.
        sr = make_shift_request(self.alice, status=ShiftRequest.Status.DRAFT)
        self.client.force_login(self.manager.user)
        response = self.client.get(reverse("shift_request_detail", args=[sr.pk]))
        self.assertNotContains(response, "Find coverage now")

    def test_hides_cancel_button_on_someone_elses_request(self):
        sr = make_shift_request(self.alice, status=ShiftRequest.Status.DRAFT)
        self.client.force_login(self.manager.user)
        response = self.client.get(reverse("shift_request_detail", args=[sr.pk]))
        self.assertNotContains(response, "Cancel request")
