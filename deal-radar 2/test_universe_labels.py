"""A missing announcement record is not a verified negative."""
from datetime import date, timedelta

from predictive.universe import label_window


def test_an_incomplete_record_is_not_a_negative():
    snapshot = date(2021, 6, 1)
    label, reason = label_window([], snapshot, 30, date(2026, 11, 9), record_complete=False)
    assert label is None
    assert reason == "announcement record is incomplete"
    phrase_miss = label_window([], snapshot, 30, date(2026, 11, 9), record_complete=False)
    assert phrase_miss[0] != 0


def test_horizons_are_distinct_and_a_closed_window_can_be_zero():
    snapshot = date(2021, 6, 1)
    announced = snapshot + timedelta(days=45)
    today = date(2026, 11, 9)
    assert label_window([announced], snapshot, 30, today, False)[0] is None
    assert label_window([announced], snapshot, 60, today, False) == (1, "verified announcement")
    assert label_window([announced], snapshot, 90, today, False) == (1, "verified announcement")
    assert label_window([], snapshot, 30, today, True) == (0, "complete window and no verified announcement")


def test_an_open_window_is_censored():
    snapshot = date(2026, 11, 1)
    label, reason = label_window([], snapshot, 30, date(2026, 11, 9), record_complete=True)
    assert label is None and reason == "censored"


if __name__ == "__main__":
    test_an_incomplete_record_is_not_a_negative()
    test_horizons_are_distinct_and_a_closed_window_can_be_zero()
    test_an_open_window_is_censored()
    print("ok")
