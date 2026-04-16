#!/usr/bin/env python3
"""Unit tests for daily_check.py business logic."""
import datetime as dt
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Patch ROOT/BOOKINGS_FILE before importing so tests don't touch real files
_tmp = tempfile.mkdtemp()
_tmp_bookings = Path(_tmp) / "bookings.json"

import daily_check as dc
dc.BOOKINGS_FILE = _tmp_bookings


class TestFridayOfSameWeek:
    def test_saturday(self):
        # 2026-04-18 is Saturday
        sat = dt.date(2026, 4, 18)
        assert sat.weekday() == 5
        fri = dc.friday_of_same_week(sat)
        assert fri == dt.date(2026, 4, 17)
        assert fri.weekday() == 4

    def test_friday(self):
        fri = dt.date(2026, 4, 17)
        assert dc.friday_of_same_week(fri) == fri

    def test_tuesday(self):
        tue = dt.date(2026, 4, 14)
        assert tue.weekday() == 1
        fri = dc.friday_of_same_week(tue)
        assert fri == dt.date(2026, 4, 17)


class TestShouldBook:
    def setup_method(self):
        # Clear bookings between tests
        if _tmp_bookings.exists():
            _tmp_bookings.unlink()

    def test_tuesday(self):
        tue = dt.date(2026, 4, 14)
        assert tue.weekday() == 1
        ok, reason = dc.should_book(tue)
        assert ok is True
        assert "booking day" in reason

    def test_friday(self):
        fri = dt.date(2026, 4, 17)
        ok, reason = dc.should_book(fri)
        assert ok is True

    def test_saturday(self):
        sat = dt.date(2026, 4, 18)
        ok, reason = dc.should_book(sat)
        assert ok is True

    def test_wednesday_no_book(self):
        wed = dt.date(2026, 4, 15)
        assert wed.weekday() == 2
        ok, reason = dc.should_book(wed)
        assert ok is False
        assert "not a booking day" in reason

    def test_saturday_skip_if_friday_booked(self):
        sat = dt.date(2026, 4, 18)
        fri = dt.date(2026, 4, 17)
        # Book Friday
        dc.save_booking(fri, "19:00", "20:00")
        ok, reason = dc.should_book(sat)
        assert ok is False
        assert "Friday" in reason

    def test_saturday_ok_if_friday_not_booked(self):
        sat = dt.date(2026, 4, 18)
        ok, reason = dc.should_book(sat)
        assert ok is True

    def test_already_booked(self):
        tue = dt.date(2026, 4, 14)
        dc.save_booking(tue, "19:00", "20:00")
        ok, reason = dc.should_book(tue)
        assert ok is False
        assert "already booked" in reason


class TestFindBest1hSlot:
    def _make_slot(self, hour, minute, courts=2):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/Los_Angeles")
        start = dt.datetime(2026, 4, 14, hour, minute, tzinfo=tz)
        end = start + dt.timedelta(minutes=30)
        return {
            "start": start,
            "end": end,
            "available_courts": courts,
            "in_past": False,
            "closed": False,
        }

    def test_two_consecutive_slots(self):
        slots = [self._make_slot(19, 0), self._make_slot(19, 30)]
        best = dc.find_best_1h_slot(slots)
        assert best is not None
        assert best["start_time"].hour == 19
        assert best["start_time"].minute == 0
        assert best["end_time"].hour == 20
        assert best["end_time"].minute == 0

    def test_prefers_earliest(self):
        slots = [
            self._make_slot(19, 0), self._make_slot(19, 30),
            self._make_slot(20, 0), self._make_slot(20, 30),
        ]
        best = dc.find_best_1h_slot(slots)
        assert best["start_time"].hour == 19

    def test_gap_skips_non_consecutive(self):
        # 19:00-19:30 and 20:00-20:30 — not consecutive
        slots = [self._make_slot(19, 0), self._make_slot(20, 0)]
        best = dc.find_best_1h_slot(slots)
        assert best is None

    def test_no_slots(self):
        assert dc.find_best_1h_slot([]) is None

    def test_single_slot(self):
        slots = [self._make_slot(19, 0)]
        assert dc.find_best_1h_slot(slots) is None

    def test_one_slot_no_courts(self):
        slots = [self._make_slot(19, 0, courts=0), self._make_slot(19, 30)]
        # filter_evening would remove courts=0, but find_best_1h_slot checks too
        # Actually find_best_1h_slot checks available_courts > 0
        best = dc.find_best_1h_slot(slots)
        assert best is None  # first slot has 0 courts

    def test_second_pair_when_first_incomplete(self):
        slots = [
            self._make_slot(19, 0, courts=0),  # no courts
            self._make_slot(19, 30),
            self._make_slot(20, 0),
            self._make_slot(20, 30),
        ]
        # After filtering (courts>0): 19:30, 20:00, 20:30
        # 19:30+20:00 is consecutive → should pick that
        filtered = [s for s in slots if s["available_courts"] > 0]
        best = dc.find_best_1h_slot(filtered)
        assert best is not None
        assert best["start_time"].hour == 19
        assert best["start_time"].minute == 30


class TestBookingsLedger:
    def setup_method(self):
        if _tmp_bookings.exists():
            _tmp_bookings.unlink()

    def test_save_and_load(self):
        dc.save_booking(dt.date(2026, 4, 14), "19:00", "20:00")
        bookings = dc.load_bookings()
        assert len(bookings) == 1
        assert bookings[0]["date"] == "2026-04-14"
        assert bookings[0]["weekday"] == "Tuesday"

    def test_has_booking(self):
        dc.save_booking(dt.date(2026, 4, 14), "19:00", "20:00")
        assert dc.has_booking_for_date(dt.date(2026, 4, 14)) is True
        assert dc.has_booking_for_date(dt.date(2026, 4, 15)) is False

    def test_empty_bookings(self):
        assert dc.load_bookings() == []
        assert dc.has_booking_for_date(dt.date(2026, 4, 14)) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
