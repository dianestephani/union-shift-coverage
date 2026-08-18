from django.shortcuts import render

from ..models import Employee
from .common import get_logged_in_employee, login_required_employee, paginate


@login_required_employee
def roster(request):
    employee = get_logged_in_employee(request)
    employees = Employee.objects.all().order_by("seniority_rank")
    return render(request, "coverage/roster.html", {
        "employee": employee,
        "employees_page": paginate(request, employees),
    })
