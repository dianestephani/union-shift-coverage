"""Small helpers for building test fixtures without a factory library."""

import datetime

from django.contrib.auth import get_user_model

from coverage.models import Employee, ShiftRequest

User = get_user_model()


def make_employee(name, seniority_rank, email=None, is_active=True, link_user=True, is_manager=False):
    """
    Create an Employee, optionally with a linked auth User (simulating a
    completed Google login) so it can be used with Client.force_login.
    """
    email = email or f"{name.lower()}@example.com"
    user = None
    if link_user:
        user = User.objects.create_user(username=name.lower(), email=email)
    return Employee.objects.create(
        name=name,
        email=email,
        user=user,
        seniority_rank=seniority_rank,
        is_active=is_active,
        is_manager=is_manager,
    )


def make_shift_request(requester, **overrides):
    defaults = dict(
        shift_date=datetime.date(2026, 8, 20),
        start_time=datetime.time(9, 0),
        end_time=datetime.time(17, 0),
    )
    defaults.update(overrides)
    return ShiftRequest.objects.create(requester=requester, **defaults)
