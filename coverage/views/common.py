"""
Shared building blocks used across the views/ package: auth helpers,
decorators, and small utilities that don't belong to any one feature area.
"""
import logging
from functools import wraps

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

logger = logging.getLogger(__name__)

PAGE_SIZE = 20


def paginate(request, queryset, per_page=PAGE_SIZE, param="page"):
    """
    Return a Django Page object for `queryset`, reading the page number
    from `request.GET[param]`. `param` lets a single page host more than
    one paginated list (e.g. requests_page / responses_page) without them
    fighting over the same query string key.
    """
    paginator = Paginator(queryset, per_page)
    return paginator.get_page(request.GET.get(param))


def safe_next_url(request, fallback):
    """
    Only redirect to a `next` value if it points back at this site.
    Without this check, a `next` param crafted by an attacker (this is a
    plain POST field, not something Django signs) could send a logged-in
    user off to an external phishing page.
    """
    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return fallback


def get_logged_in_employee(request):
    if not request.user.is_authenticated:
        return None
    return getattr(request.user, "employee", None)


def login_required_employee(view_func):
    """Simple decorator – redirects to login if no linked employee."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not get_logged_in_employee(request):
            return redirect("login")
        return view_func(request, *args, **kwargs)

    return wrapper


def manager_required(view_func):
    """
    Redirects to login if not logged in, and 404s (rather than a 403 that
    would reveal the page exists) if the employee isn't a manager.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        employee = get_logged_in_employee(request)
        if not employee:
            return redirect("login")
        if not employee.is_manager:
            raise Http404
        return view_func(request, *args, **kwargs)

    return wrapper
