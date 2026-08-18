from django import forms
from django.utils import timezone
from .models import ShiftRequest


class ShiftRequestForm(forms.ModelForm):
    class Meta:
        model = ShiftRequest
        fields = ["shift_date", "start_time", "end_time", "notes"]
        widgets = {
            "shift_date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Any relevant details…"}),
        }
        labels = {
            "shift_date": "Date",
            "start_time": "Start time",
            "end_time": "End time",
            "notes": "Notes (optional)",
        }

    def clean_shift_date(self):
        shift_date = self.cleaned_data["shift_date"]
        if shift_date < timezone.localdate():
            raise forms.ValidationError("Shift date can't be in the past.")
        return shift_date

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")
        if start_time and end_time and end_time <= start_time:
            raise forms.ValidationError("End time must be after start time.")
        return cleaned_data
