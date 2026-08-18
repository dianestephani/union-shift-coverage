from django.conf import settings
from django.db import models
from phonenumber_field.modelfields import PhoneNumberField

from .time_format import uses_24h_time

# A curated subset of IANA timezone names, rather than the full ~350-entry
# zoneinfo database, so the settings page dropdown stays easy to scan.
TIMEZONE_CHOICES = [
    ("Pacific/Honolulu", "Hawaii Time"),
    ("America/Anchorage", "Alaska Time"),
    ("America/Los_Angeles", "Pacific Time"),
    ("America/Denver", "Mountain Time"),
    ("America/Phoenix", "Arizona Time (no DST)"),
    ("America/Chicago", "Central Time"),
    ("America/New_York", "Eastern Time"),
    ("America/Sao_Paulo", "Brasília Time"),
    ("UTC", "UTC"),
    ("Europe/London", "London"),
    ("Europe/Paris", "Central European Time"),
    ("Europe/Moscow", "Moscow Time"),
    ("Africa/Cairo", "Cairo"),
    ("Africa/Johannesburg", "Johannesburg"),
    ("Asia/Dubai", "Gulf Standard Time"),
    ("Asia/Kolkata", "India Standard Time"),
    ("Asia/Shanghai", "China Standard Time"),
    ("Asia/Tokyo", "Japan Standard Time"),
    ("Asia/Singapore", "Singapore"),
    ("Australia/Sydney", "Sydney"),
    ("Pacific/Auckland", "Auckland"),
]


class Employee(models.Model):
    """
    Represents a staff member. seniority_rank is 1-based:
    rank 1 = most senior. Coverage requests cascade from the
    requester downward (higher rank numbers = less senior).
    """

    name = models.CharField(max_length=100)
    email = models.EmailField(
        unique=True,
        null=True,
        blank=True,
        help_text="Must match the Google account used to log in.",
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee",
    )
    phone_number = PhoneNumberField(unique=True, null=True, blank=True)
    seniority_rank = models.PositiveIntegerField(
        unique=True,
        help_text="1 = most senior. Lower numbers have higher seniority.",
    )
    is_active = models.BooleanField(default=True)
    is_manager = models.BooleanField(
        default=False,
        help_text="Managers can see every open request, the full roster, and each employee's history.",
    )
    timezone = models.CharField(
        max_length=64,
        choices=TIMEZONE_CHOICES,
        default="America/Chicago",
        help_text="Timestamps you see in the app (notifications, request history) are shown in this timezone.",
    )
    military_time = models.BooleanField(
        default=False,
        help_text="Show times like 14:00 instead of 2:00 PM.",
    )

    class Meta:
        ordering = ["seniority_rank"]

    def __str__(self):
        return f"#{self.seniority_rank} {self.name}"

    def get_phone_e164(self):
        return str(self.phone_number)

    def get_next_in_roster(self):
        """Return the next less-senior active employee, or None."""
        return (
            Employee.objects.filter(
                seniority_rank__gt=self.seniority_rank,
                is_active=True,
            )
            .order_by("seniority_rank")
            .first()
        )


class ShiftRequest(models.Model):
    """A request to find coverage for a shift."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SEARCHING = "SEARCHING", "Searching"
        COVERED = "COVERED", "Covered"
        UNCOVERED = "UNCOVERED", "Uncovered"  # exhausted entire roster

    requester = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="shift_requests"
    )
    shift_date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    # The employee currently being asked (None once covered/exhausted)
    current_candidate = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pending_coverage_asks",
    )
    covered_by = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="covered_shifts",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"ShiftRequest #{self.pk} – {self.requester.name} on {self.shift_date}"

    def day_display(self):
        return self.shift_date.strftime("%A")

    def date_display(self):
        return self.shift_date.strftime("%B %-d, %Y")

    def time_display(self):
        fmt = "%H:%M" if uses_24h_time() else "%-I:%M %p"
        start = self.start_time.strftime(fmt)
        end = self.end_time.strftime(fmt)
        return f"{start}–{end}"


class ShiftResponse(models.Model):
    """
    Tracks each employee's response to a coverage request.
    One row per (shift_request, employee) pair.
    """

    class Answer(models.TextChoices):
        PENDING = "PENDING", "Pending"
        YES = "YES", "Yes"
        NO = "NO", "No"

    shift_request = models.ForeignKey(
        ShiftRequest, on_delete=models.CASCADE, related_name="responses"
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="shift_responses"
    )
    answer = models.CharField(
        max_length=20, choices=Answer.choices, default=Answer.PENDING
    )
    # When the ask notification was sent
    asked_at = models.DateTimeField(auto_now_add=True)
    # When the employee replied
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("shift_request", "employee")]
        ordering = ["asked_at"]

    def __str__(self):
        return f"{self.employee.name} → {self.answer} (ShiftRequest #{self.shift_request_id})"


class CoverageEvent(models.Model):
    """
    Immutable audit log. One row per state change in the coverage process.
    """

    class EventType(models.TextChoices):
        REQUEST_CREATED = "REQUEST_CREATED", "Request created"
        REQUEST_ACTIVATED = "REQUEST_ACTIVATED", "Coverage search started"
        NOTIFICATION_SENT = "NOTIFICATION_SENT", "Notification sent"
        RESPONSE_RECEIVED = "RESPONSE_RECEIVED", "Response received"
        COVERED = "COVERED", "Shift covered"
        UNCOVERED = "UNCOVERED", "Roster exhausted – not covered"

    shift_request = models.ForeignKey(
        ShiftRequest, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"[{self.event_type}] ShiftRequest #{self.shift_request_id} @ {self.created_at:%Y-%m-%d %H:%M}"


class Notification(models.Model):
    """
    An in-app notification for an employee. If action_response is set,
    the notification is actionable (renders YES/NO buttons tied to that
    ShiftResponse); otherwise it's purely informational.
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="notifications"
    )
    shift_request = models.ForeignKey(
        ShiftRequest, on_delete=models.CASCADE, related_name="notifications"
    )
    action_response = models.ForeignKey(
        ShiftResponse,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Notification for {self.employee.name}: {self.message[:40]}"
