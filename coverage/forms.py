from django import forms
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
