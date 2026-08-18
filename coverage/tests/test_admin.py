from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from coverage import coverage_service
from coverage.models import Employee
from .factories import make_employee, make_shift_request

User = get_user_model()


class AdminSmokeTests(TestCase):
    """
    Each registered ModelAdmin's changelist should render without error.
    A broken list_display (e.g. referencing a removed field/method) throws
    a 500 here rather than failing silently, which is the main risk on
    admin.py since it has no other logic to test.
    """

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="password"
        )
        self.client.force_login(self.superuser)

        alice = make_employee("Alice", seniority_rank=1)
        make_employee("Bob", seniority_rank=2)
        sr = make_shift_request(alice)
        coverage_service.start_coverage_search(sr)

    def test_employee_changelist_loads(self):
        response = self.client.get(reverse("admin:coverage_employee_changelist"))
        self.assertEqual(response.status_code, 200)

    def test_shift_request_changelist_loads(self):
        response = self.client.get(reverse("admin:coverage_shiftrequest_changelist"))
        self.assertEqual(response.status_code, 200)

    def test_shift_response_changelist_loads(self):
        response = self.client.get(reverse("admin:coverage_shiftresponse_changelist"))
        self.assertEqual(response.status_code, 200)

    def test_coverage_event_changelist_loads(self):
        response = self.client.get(reverse("admin:coverage_coverageevent_changelist"))
        self.assertEqual(response.status_code, 200)

    def test_notification_changelist_loads(self):
        response = self.client.get(reverse("admin:coverage_notification_changelist"))
        self.assertEqual(response.status_code, 200)


class EmployeeBulkEditTests(TestCase):
    """
    Exercises the Employee changelist's list_editable bulk-save flow
    (edit seniority_rank/is_active/is_manager for several rows and hit
    Save) — the one place raw HTTP form data reaches the admin instead of
    a normal single-object form, and the one place `seniority_rank`'s
    unique constraint can actually be violated by admin usage.
    """

    def setUp(self):
        self.superuser = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="password"
        )
        self.client.force_login(self.superuser)
        self.alice = make_employee("Alice", seniority_rank=1)
        self.bob = make_employee("Bob", seniority_rank=2)

    def _bulk_edit_payload(self, employees, overrides):
        """
        Build POST data for the changelist's list_editable formset.
        `overrides` is {employee_pk: {"seniority_rank": N}}; any row not
        mentioned is submitted with its current values unchanged.
        """
        data = {
            "form-TOTAL_FORMS": str(len(employees)),
            "form-INITIAL_FORMS": str(len(employees)),
            "form-MIN_NUM_FORMS": "0",
            "form-MAX_NUM_FORMS": "1000",
            "_save": "Save",
        }
        for i, e in enumerate(employees):
            fields = overrides.get(e.pk, {})
            data[f"form-{i}-id"] = str(e.pk)
            data[f"form-{i}-seniority_rank"] = str(fields.get("seniority_rank", e.seniority_rank))
            if fields.get("is_active", e.is_active):
                data[f"form-{i}-is_active"] = "on"
            if fields.get("is_manager", e.is_manager):
                data[f"form-{i}-is_manager"] = "on"
        return data

    def test_bulk_edit_duplicate_seniority_rank_shows_friendly_error_not_500(self):
        employees = list(Employee.objects.order_by("seniority_rank"))
        data = self._bulk_edit_payload(
            employees, {self.bob.pk: {"seniority_rank": self.alice.seniority_rank}}
        )
        response = self.client.post(reverse("admin:coverage_employee_changelist"), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "must be unique")

        self.alice.refresh_from_db()
        self.bob.refresh_from_db()
        self.assertNotEqual(self.alice.seniority_rank, self.bob.seniority_rank)

    def test_bulk_edit_can_swap_two_ranks(self):
        # This is exactly the case a naive one-row-at-a-time save would
        # transiently collide on, even though the end state is valid.
        employees = list(Employee.objects.order_by("seniority_rank"))
        data = self._bulk_edit_payload(employees, {
            self.alice.pk: {"seniority_rank": self.bob.seniority_rank},
            self.bob.pk: {"seniority_rank": self.alice.seniority_rank},
        })
        response = self.client.post(reverse("admin:coverage_employee_changelist"), data, follow=True)

        self.assertEqual(response.status_code, 200)
        self.alice.refresh_from_db()
        self.bob.refresh_from_db()
        self.assertEqual(self.alice.seniority_rank, 2)
        self.assertEqual(self.bob.seniority_rank, 1)

    def test_bulk_edit_rejects_collision_with_an_unedited_employee(self):
        carol = make_employee("Carol", seniority_rank=3)
        # Only Bob is being edited here — Carol isn't part of this batch at all.
        employees = list(Employee.objects.order_by("seniority_rank"))
        data = self._bulk_edit_payload(employees, {self.bob.pk: {"seniority_rank": 3}})
        response = self.client.post(reverse("admin:coverage_employee_changelist"), data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "must be unique")

        self.bob.refresh_from_db()
        carol.refresh_from_db()
        self.assertEqual(self.bob.seniority_rank, 2)
        self.assertEqual(carol.seniority_rank, 3)

    def test_bulk_edit_valid_single_change_still_works(self):
        employees = list(Employee.objects.order_by("seniority_rank"))
        data = self._bulk_edit_payload(employees, {self.bob.pk: {"is_manager": True}})
        response = self.client.post(reverse("admin:coverage_employee_changelist"), data, follow=True)

        self.assertEqual(response.status_code, 200)
        self.bob.refresh_from_db()
        self.assertTrue(self.bob.is_manager)
