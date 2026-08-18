from django.test import TestCase

from coverage.forms import ShiftRequestForm


class ShiftRequestFormTests(TestCase):
    def valid_data(self, **overrides):
        data = {
            "shift_date": "2026-08-20",
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

    def test_end_time_before_start_time_is_currently_accepted(self):
        # Pinning current behavior: the form has no cross-field validation,
        # so an end time earlier than the start time is accepted as-is.
        # If that ever needs to become a validation error, this test should
        # be the one that flips.
        form = ShiftRequestForm(self.valid_data(start_time="17:00", end_time="09:00"))
        self.assertTrue(form.is_valid(), form.errors)

    def test_past_shift_date_is_currently_accepted(self):
        # Same as above: no validation prevents requesting coverage for a
        # date that's already passed.
        form = ShiftRequestForm(self.valid_data(shift_date="2020-01-01"))
        self.assertTrue(form.is_valid(), form.errors)
