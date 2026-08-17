from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from coverage.adapters import CoverageSocialAccountAdapter
from coverage.models import Employee
from coverage.signals import link_employee_to_user

User = get_user_model()


def fake_sociallogin(email, is_existing=False):
    """
    Minimal stand-in for allauth's SocialLogin — CoverageSocialAccountAdapter
    only reads `.is_existing` and `.user.email`.
    """
    return SimpleNamespace(is_existing=is_existing, user=SimpleNamespace(email=email))


class SocialAccountAdapterTests(TestCase):
    def setUp(self):
        self.adapter = CoverageSocialAccountAdapter()

    def test_allows_login_for_matching_employee_email(self):
        Employee.objects.create(name="Alice", email="alice@example.com", seniority_rank=1)
        # Should not raise.
        self.adapter.pre_social_login(None, fake_sociallogin("alice@example.com"))

    def test_matches_case_insensitively(self):
        Employee.objects.create(name="Alice", email="alice@example.com", seniority_rank=1)
        self.adapter.pre_social_login(None, fake_sociallogin("Alice@Example.com"))

    def test_rejects_login_with_no_matching_employee(self):
        with self.assertRaises(PermissionDenied):
            self.adapter.pre_social_login(None, fake_sociallogin("nobody@example.com"))

    def test_skips_check_for_existing_social_account(self):
        # Once a SocialAccount is already linked, allauth is just doing a
        # normal login, not a signup — no employee lookup needed/possible.
        self.adapter.pre_social_login(None, fake_sociallogin("whatever@example.com", is_existing=True))


class LinkEmployeeToUserSignalTests(TestCase):
    def test_links_matching_employee_by_email(self):
        employee = Employee.objects.create(name="Alice", email="alice@example.com", seniority_rank=1)
        user = User.objects.create_user(username="alice", email="alice@example.com")

        link_employee_to_user(sender=None, request=None, user=user)

        employee.refresh_from_db()
        self.assertEqual(employee.user, user)

    def test_does_not_relink_already_linked_employee(self):
        original_user = User.objects.create_user(username="alice1", email="alice@example.com")
        employee = Employee.objects.create(
            name="Alice", email="alice@example.com", seniority_rank=1, user=original_user
        )
        new_user = User.objects.create_user(username="alice2", email="alice@example.com")

        link_employee_to_user(sender=None, request=None, user=new_user)

        employee.refresh_from_db()
        self.assertEqual(employee.user, original_user)

    def test_no_matching_employee_is_a_noop(self):
        user = User.objects.create_user(username="nobody", email="nobody@example.com")
        # Should not raise even though no Employee exists.
        link_employee_to_user(sender=None, request=None, user=user)
