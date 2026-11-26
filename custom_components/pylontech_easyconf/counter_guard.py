"""Which value of an energy counter to show, read by read.

The BMS's energy counters only rise, except a day's counters, which go back to
zero once a day. A single wrong reading still happens: a Solarman logger that
another client polls too sometimes hands one client the other's answer, and an
answer of the same length passes every check of the frame. Shown as it is, a
wrong reading gives Home Assistant's energy statistics a false meter reset or
a false jump.

So a reading that breaks the counter's rules is held back, and the last value
stays. The held-back reading is believed only once ``CONFIRM_READS`` readings in
a row agree with it: a wrong answer is a one-off, a real change stays. Without
that a counter could stick: a false lower value believed mid-day made every
true value after it look like a jump, until midnight; and a battery that moved
more energy while Home Assistant was down than one poll allows looked like a
jump for good.

Pure Python, with no Home Assistant, so that it can be tested on its own.
"""

from __future__ import annotations

#: The most a battery could charge or discharge, with room to spare: a counter
#: that climbs faster than this is not counting energy.
MAX_KW = 60.0
#: Readings in a row that must agree before a value that breaks the rules is
#: believed.
CONFIRM_READS = 3

DAILY = "daily"
LIFETIME = "lifetime"


def rise_limit(since: float | None, now: float, interval: float) -> float:
    """How far a counter can rise, in kWh, between a reading at ``since`` and
    one at ``now`` (seconds). With ``since`` unknown, one poll interval."""
    seconds = interval if since is None else max(now - since, interval)
    return 1.0 + MAX_KW * seconds / 3600


class CounterGuard:
    """The shown value of one energy counter.

    ``kind`` is ``DAILY`` (back to zero once a day) or ``LIFETIME`` (never
    down). ``last`` is the value shown before, e.g. restored after a restart.
    """

    def __init__(self, kind: str, last: float | None = None) -> None:
        self.kind = kind
        #: The value shown, and when it was read (None for a restored value).
        self.last = last
        self.last_at: float | None = None
        #: The latest held-back reading, when it was read, and how many
        #: readings in a row have agreed with it.
        self.held: float | None = None
        self.held_at: float | None = None
        self.held_count = 0

    def read(self, value: float, now: float, interval: float) -> float:
        """The value to show for a new reading taken at ``now`` (seconds)."""
        if self.last is None or 0 <= value - self.last <= rise_limit(self.last_at, now, interval):
            return self._believe(value, now)
        if self.kind == LIFETIME and value < self.last:
            # Never believed, however often it comes: a false lower value
            # believed and then the true one again would count the battery's
            # whole lifetime once more in the energy statistics.
            return self.last
        if self.held is not None and 0 <= value - self.held <= rise_limit(
            self.held_at, now, interval
        ):
            self.held_count += 1
        else:
            self.held_count = 1
        self.held, self.held_at = value, now
        if self.held_count >= CONFIRM_READS:
            return self._believe(value, now)
        return self.last

    def _believe(self, value: float, now: float) -> float:
        self.last, self.last_at = value, now
        self.held, self.held_at, self.held_count = None, None, 0
        return value
