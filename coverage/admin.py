from django import forms
from django.contrib import admin
from .models import CoverageEvent, Employee, Notification, ShiftRequest, ShiftResponse


class EmployeeChangeListForm(forms.ModelForm):
    """
    The per-row form behind the changelist's list_editable bulk-edit.

    A plain ModelForm validates seniority_rank's uniqueness against
    whatever's *currently saved* in the database — it has no way to know
    another row in the same batch is also about to change. That makes it
    reject a perfectly valid swap (Alice 1<->2 Bob) as a false conflict,
    because at validation time Bob's row still shows rank 2 in the DB.
    Cross-row uniqueness is exactly what EmployeeChangeListFormSet.clean()
    below checks instead, so the single-row check is disabled here to
    avoid the two disagreeing.
    """

    class Meta:
        model = Employee
        fields = []  # modelformset_factory injects the real fields (list_editable)

    def _get_validation_exclusions(self):
        # Returns a set in modern Django, a list in older versions —
        # union/add covers both without caring which.
        exclusions = super()._get_validation_exclusions()
        return set(exclusions) | {"seniority_rank"}


class EmployeeChangeListFormSet(forms.BaseModelFormSet):
    """
    Backs the "edit multiple rows and Save" flow on the Employee changelist
    (list_editable). Without this, a bulk edit that leaves two employees
    with the same seniority_rank hits the model's `unique=True` constraint
    at the database layer instead of at the form layer — which surfaces to
    the admin as a raw IntegrityError / 500 page rather than the normal
    "please correct the error below" validation message every other admin
    form failure shows.
    """

    def clean(self):
        super().clean()
        if any(self.errors):
            return

        target_ranks = {}  # seniority_rank -> [employee names]
        edited_pks = set()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            instance = form.instance
            edited_pks.add(instance.pk)
            rank = form.cleaned_data.get("seniority_rank", instance.seniority_rank)
            name = form.cleaned_data.get("name", instance.name)
            target_ranks.setdefault(rank, []).append(name)

        duplicates = {rank: names for rank, names in target_ranks.items() if len(names) > 1}

        # Also catch a target rank colliding with someone who isn't part of
        # this edit at all (not on this changelist page, for example).
        conflicts_outside_batch = Employee.objects.filter(
            seniority_rank__in=target_ranks.keys()
        ).exclude(pk__in=edited_pks)
        for employee in conflicts_outside_batch:
            duplicates.setdefault(employee.seniority_rank, []).append(f"{employee.name} (unchanged)")

        if duplicates:
            details = "; ".join(
                f"#{rank}: {', '.join(names)}" for rank, names in sorted(duplicates.items())
            )
            raise forms.ValidationError(
                "Seniority rank must be unique for each employee — these would end up "
                f"sharing a rank: {details}. Double check your edits and try again."
            )


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = [
        "seniority_rank", "name", "email", "phone_number", "timezone",
        "military_time", "user", "is_active", "is_manager",
    ]
    list_display_links = ["name"]
    list_editable = ["seniority_rank", "is_active", "is_manager"]
    ordering = ["seniority_rank"]

    def get_changelist_form(self, request, **kwargs):
        return EmployeeChangeListForm

    def get_changelist_formset(self, request, **kwargs):
        kwargs["formset"] = EmployeeChangeListFormSet
        return super().get_changelist_formset(request, **kwargs)

    def save_model(self, request, obj, form, change):
        # The changelist's bulk "Save" (list_editable) saves each changed
        # row one at a time inside a single transaction, in changelist
        # order — it doesn't know about sibling rows also being saved in
        # the same submission. So saving a legitimate swap (Alice 1<->2 Bob)
        # can transiently collide with whichever row hasn't saved yet, even
        # though EmployeeChangeListFormSet.clean() already confirmed the
        # *final* state is conflict-free. Bump whoever currently holds the
        # target rank out of the way first: if they're also being edited
        # this batch, their own save (later in the same transaction)
        # applies their real target rank over this placeholder; if they're
        # not, clean() would already have rejected the whole submission
        # before any saving started, so this situation can't arise from a
        # single-user submission — only a genuine race with a concurrent
        # admin edit could still hit the constraint here, which is an
        # acceptable, rare edge to leave as a 500 rather than add
        # significant complexity for.
        if change and "seniority_rank" in form.changed_data:
            occupant = Employee.objects.filter(
                seniority_rank=obj.seniority_rank
            ).exclude(pk=obj.pk).first()
            if occupant:
                # seniority_rank is a PositiveIntegerField (DB-level CHECK
                # constraint >= 0), so the placeholder has to stay positive.
                # Offsetting by the pk keeps it unique even if more than one
                # occupant gets bumped in the same submission.
                placeholder = 1_000_000 + occupant.pk
                Employee.objects.filter(pk=occupant.pk).update(seniority_rank=placeholder)
        super().save_model(request, obj, form, change)


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
