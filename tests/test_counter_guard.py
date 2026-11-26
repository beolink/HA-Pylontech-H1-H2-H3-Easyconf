"""Which value of an energy counter is shown (counter_guard.py): a wrong reading
held back, a real change believed once readings agree, and no counter stuck."""

import pytest

from custom_components.pylontech_easyconf.counter_guard import (
    CONFIRM_READS,
    DAILY,
    LIFETIME,
    CounterGuard,
)

INTERVAL = 60.0


def shown(guard, values, start=0.0, step=INTERVAL):
    """The values shown for readings taken one interval apart."""
    return [guard.read(v, start + i * step, INTERVAL) for i, v in enumerate(values)]


def test_a_rising_counter_is_shown_as_it_is():
    guard = CounterGuard(DAILY)
    assert shown(guard, [1.0, 1.2, 1.2, 2.5]) == [1.0, 1.2, 1.2, 2.5]


def test_a_wrong_lower_reading_mid_day_is_held_and_the_counter_goes_on():
    # Up to 0.1.5 a day's counter believed any fall, so a wrong lower
    # reading became the last value, and every true value after it was
    # refused as a jump until midnight.
    guard = CounterGuard(DAILY)
    assert shown(guard, [12.9, 5.0, 13.0, 13.1]) == [12.9, 12.9, 13.0, 13.1]


def test_a_wrong_higher_reading_is_held_and_the_counter_goes_on():
    guard = CounterGuard(DAILY)
    assert shown(guard, [12.9, 40.0, 13.0]) == [12.9, 12.9, 13.0]


def test_the_midnight_reset_is_believed_once_readings_agree():
    guard = CounterGuard(DAILY)
    values = [21.4, 0.0, 0.01, 0.03, 0.05]
    assert shown(guard, values) == [21.4, 21.4, 21.4, 0.03, 0.05]
    assert CONFIRM_READS == 3


def test_a_wrong_answer_in_the_middle_of_the_reset_only_delays_it():
    guard = CounterGuard(DAILY)
    values = [21.4, 0.0, 0.01, 9.0, 0.02, 0.03, 0.04]
    assert shown(guard, values)[-1] == 0.04
    assert guard.last == 0.04


def test_answers_that_do_not_agree_with_each_other_are_never_believed():
    guard = CounterGuard(DAILY)
    values = [12.9, 5.0, 30.0, 4.0, 31.0, 3.0, 32.0]
    assert shown(guard, values) == [12.9] * len(values)


def test_a_lifetime_counter_never_goes_down():
    guard = CounterGuard(LIFETIME)
    assert shown(guard, [9192.0] + [0.0] * 10) == [9192.0] * 11


def test_energy_moved_while_home_assistant_was_down_is_believed_once_readings_agree():
    # Restored after a restart: when the last value was read is unknown, so a
    # rise of more than one poll is held. Up to 0.1.5 it was refused for good.
    guard = CounterGuard(LIFETIME, last=9192.0)
    assert shown(guard, [9203.0, 9203.0, 9204.0, 9204.0]) == [9192.0, 9192.0, 9204.0, 9204.0]
    daily = CounterGuard(DAILY, last=3.0)
    assert shown(daily, [12.0, 12.1, 12.2]) == [3.0, 3.0, 12.2]


def test_the_rise_allowed_grows_with_the_time_since_the_last_reading():
    guard = CounterGuard(DAILY)
    guard.read(3.0, 0.0, INTERVAL)
    # Half an hour without a reading: 1 kWh + 60 kW for 0.5 h.
    assert guard.read(31.0, 1800.0, INTERVAL) == 31.0
    assert guard.read(70.0, 1860.0, INTERVAL) == 31.0


def test_a_restored_day_counter_from_yesterday_goes_back_to_zero():
    guard = CounterGuard(DAILY, last=20.0)
    assert shown(guard, [5.0, 5.1, 5.2, 5.3]) == [20.0, 20.0, 5.2, 5.3]


@pytest.mark.parametrize("kind", [DAILY, LIFETIME])
def test_the_first_reading_is_shown_as_it_is(kind):
    assert CounterGuard(kind).read(8219.0, 0.0, INTERVAL) == 8219.0
