from django.contrib import messages
from django.shortcuts import redirect, render

from ..forms import EmployeeSettingsForm
from .common import get_logged_in_employee, login_required_employee


@login_required_employee
def settings_page(request):
    employee = get_logged_in_employee(request)
    form = EmployeeSettingsForm(request.POST or None, instance=employee)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Settings saved.")
        return redirect("settings")

    return render(request, "coverage/settings.html", {
        "employee": employee,
        "form": form,
    })
