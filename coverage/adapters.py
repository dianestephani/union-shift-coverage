from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.core.exceptions import PermissionDenied

from .models import Employee


class CoverageSocialAccountAdapter(DefaultSocialAccountAdapter):
    """
    Employees are provisioned ahead of time via /admin/ with a matching
    email address. Reject any Google login whose email doesn't match an
    existing Employee, rather than allowing open signup.
    """

    def pre_social_login(self, request, sociallogin):
        if sociallogin.is_existing:
            return
        email = sociallogin.user.email
        if not email or not Employee.objects.filter(email__iexact=email).exists():
            raise PermissionDenied(
                "No employee account found for that email address. "
                "Please contact your manager."
            )
