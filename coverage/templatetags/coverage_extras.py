from django import template
from django.utils import timezone as dj_timezone

from coverage.time_format import uses_24h_time

register = template.Library()


def _format(value, include_year):
    if not value:
        return ""
    local = dj_timezone.localtime(value) if dj_timezone.is_aware(value) else value
    time_fmt = "%H:%M" if uses_24h_time() else "%-I:%M %p"
    date_fmt = "%b %-d, %Y" if include_year else "%b %-d"
    return f"{local.strftime(date_fmt)}, {local.strftime(time_fmt)}"


@register.filter
def user_datetime(value):
    """Full date + time, honoring the employee's timezone and 12h/24h preference."""
    return _format(value, include_year=True)


@register.filter
def user_datetime_short(value):
    """Same as user_datetime but without the year, for tight table columns."""
    return _format(value, include_year=False)
