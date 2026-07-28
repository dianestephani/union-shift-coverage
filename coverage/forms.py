from django import forms
from .models import ShiftRequest


class PhoneLoginForm(forms.Form):
    phone_number = forms.CharField(
        max_length=20,
        label="Phone number",
        widget=forms.TextInput(attrs={"placeholder": "+1 555 000 0000", "autofocus": True}),
        help_text="Enter the phone number you registered with.",
    )

    def clean_phone_number(self):
        raw = self.cleaned_data["phone_number"]
        # Strip spaces and dashes for normalisation; views will look up E.164
        return raw.strip()


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
