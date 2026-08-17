from allauth.account.signals import user_signed_up
from django.dispatch import receiver

from .models import Employee


@receiver(user_signed_up)
def link_employee_to_user(request, user, **kwargs):
    """Attach the newly-created auth User to the matching Employee record."""
    Employee.objects.filter(email__iexact=user.email, user__isnull=True).update(user=user)
