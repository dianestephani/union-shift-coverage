import datetime

from django.test import TestCase
from django.utils import timezone

from coverage.forms import ShiftRequestForm


class ShiftRequestFormTests(TestCase):
    def valid_data(self, **overrides):
        # Relative to "today" so this test suite doesn't start failing the
        # "past date" checks once the calendar catches up to a hardcoded date.
        future_date = (timezone.localdate() + datetime.timedelta(days=14)).isoformat()
        data = {
            "shift_date": future_date,
            "start_time": "09:00",
            "end_time": "17:00",
            "notes": "",
        }
        data.update(overrides)
        return data

    def test_valid_data_passes(self):
        form = ShiftRequestForm(self.valid_data())
        self.assertTrue(form.is_valid(), form.errors)

    def test_notes_is_optional(self):
        data = self.valid_data()
        del data["notes"]
        form = ShiftRequestForm(data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_shift_date_is_invalid(self):
        data = self.valid_data()
        del data["shift_date"]
        form = ShiftRequestForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("shift_date", form.errors)

    def test_missing_start_time_is_invalid(self):
        data = self.valid_data()
        del data["start_time"]
        form = ShiftRequestForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("start_time", form.errors)

    def test_missing_end_time_is_invalid(self):
        data = self.valid_data()
        del data["end_time"]
        form = ShiftRequestForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("end_time", form.errors)

    def test_end_time_before_start_time_is_rejected(self):
        form = ShiftRequestForm(self.valid_data(start_time="17:00", end_time="09:00"))
        self.assertFalse(form.is_valid())
        self.assertIn("End time must be after start time.", form.non_field_errors())

    def test_end_time_equal_to_start_time_is_rejected(self):
        form = ShiftRequestForm(self.valid_data(start_time="09:00", end_time="09:00"))
        self.assertFalse(form.is_valid())
        self.assertIn("End time must be after start time.", form.non_field_errors())

    def test_past_shift_date_is_rejected(self):
        form = ShiftRequestForm(self.valid_data(shift_date="2020-01-01"))
        self.assertFalse(form.is_valid())
        self.assertIn("Shift date can't be in the past.", form.errors["shift_date"])

    def test_todays_date_is_accepted(self):
        form = ShiftRequestForm(self.valid_data(shift_date=timezone.localdate().isoformat()))
        self.assertTrue(form.is_valid(), form.errors)
