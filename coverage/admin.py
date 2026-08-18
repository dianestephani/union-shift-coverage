from django.contrib import admin
from .models import CoverageEvent, Employee, Notification, ShiftRequest, ShiftResponse


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ["seniority_rank", "name", "email", "phone_number", "timezone", "user", "is_active"]
    list_display_links = ["name"]
    list_editable = ["seniority_rank", "is_active"]
    ordering = ["seniority_rank"]


@admin.register(ShiftRequest)
class ShiftRequestAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "requester",
        "shift_date",
        "start_time",
        "end_time",
        "status",
        "current_candidate",
        "covered_by",
        "created_at",
    ]
    list_filter = ["status", "shift_date"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ShiftResponse)
class ShiftResponseAdmin(admin.ModelAdmin):
    list_display = ["shift_request", "employee", "answer", "asked_at", "answered_at"]
    list_filter = ["answer"]


@admin.register(CoverageEvent)
class CoverageEventAdmin(admin.ModelAdmin):
    list_display = ["created_at", "shift_request", "event_type", "employee", "message"]
    list_filter = ["event_type"]
    readonly_fields = ["created_at"]


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["created_at", "employee", "shift_request", "action_response", "read_at", "message"]
    list_filter = ["read_at"]
    readonly_fields = ["created_at"]
