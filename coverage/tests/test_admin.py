from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from coverage import coverage_service
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
