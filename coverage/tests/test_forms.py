import datetime

from django.test import TestCase
from django.utils import timezone

from coverage.forms import EmployeeSettingsForm, ShiftRequestForm
from .factories import make_employee


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


class EmployeeSettingsFormTests(TestCase):
    def setUp(self):
        self.employee = make_employee("Alice", seniority_rank=1)

    def test_valid_timezone_choice_passes(self):
        form = EmployeeSettingsForm(
            {"timezone": "Asia/Tokyo", "military_time": ""}, instance=self.employee
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_unknown_timezone_is_rejected(self):
        form = EmployeeSettingsForm(
            {"timezone": "Mars/Olympus_Mons", "military_time": ""}, instance=self.employee
        )
        self.assertFalse(form.is_valid())
        self.assertIn("timezone", form.errors)

    def test_missing_timezone_is_rejected(self):
        form = EmployeeSettingsForm({"military_time": ""}, instance=self.employee)
        self.assertFalse(form.is_valid())
        self.assertIn("timezone", form.errors)

    def test_military_time_checkbox_absent_means_false(self):
        form = EmployeeSettingsForm({"timezone": "America/Chicago"}, instance=self.employee)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertFalse(saved.military_time)

    def test_military_time_checked_means_true(self):
        form = EmployeeSettingsForm(
            {"timezone": "America/Chicago", "military_time": "on"}, instance=self.employee
        )
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertTrue(saved.military_time)

    def test_only_declared_fields_are_editable(self):
        # Guard against someone widening Meta.fields to something that would
        # let this form touch seniority_rank, is_manager, etc.
        self.assertEqual(set(EmployeeSettingsForm.Meta.fields), {"timezone", "military_time"})
