import logging

from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.core.exceptions import PermissionDenied

from .models import Employee

logger = logging.getLogger(__name__)


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

    def on_authentication_error(self, request, provider, error=None, exception=None, extra_context=None):
        # allauth renders a generic "Third-Party Login Failure" page for any
        # error here and hides the real cause in production — log it so it
        # shows up in the deploy's log stream instead of vanishing silently.
        logger.error(
            "Social login failed: provider=%s error=%s exception=%r",
            provider, error, exception, exc_info=exception,
        )
        return super().on_authentication_error(request, provider, error=error, exception=exception, extra_context=extra_context)
