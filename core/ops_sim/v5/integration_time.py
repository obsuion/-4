"""Explicit dyadic internal time; completed-state clocks remain integer seconds.

The bounded partition is a numerical request, never a convergence certificate.
Offsets are calculated from index * duration, not accumulated floating clocks.
"""

from dataclasses import dataclass
from fractions import Fraction
from math import gcd


MAX_SUBDIVISION_LEVEL = 12
MAX_ACTION_SECONDS = 2**40
MAX_PROGRAM_SUBSTEPS = 16384  # includes both requested and fallback proposals


@dataclass(frozen=True, slots=True)
class RationalSeconds:
    """Bounded canonical exact offset/duration for integer-bit/rate service.

    Zero is admitted for offsets only. Physical kernels require a positive
    duration. Conversion to binary64 is rounded once for existing equations;
    that approximation never owns boundaries or transmitted bits.
    """
    numerator: int
    denominator: int

    def __post_init__(self):
        if type(self.numerator) is not int or type(self.denominator) is not int:
            raise TypeError("rational seconds require exact built-in integers")
        if not 0 <= self.numerator <= 2**96 or not 1 <= self.denominator <= 2**64:
            raise ValueError("rational seconds exceed representability bounds")
        if gcd(self.numerator, self.denominator) != 1:
            raise ValueError("rational seconds must be canonical reduced terms")
        if self.numerator > MAX_ACTION_SECONDS * self.denominator:
            raise ValueError("rational seconds exceed the physical duration bound")

    @classmethod
    def from_fraction(cls, value):
        if type(value) is not Fraction:
            raise TypeError("exact Fraction required")
        return cls(value.numerator, value.denominator)

    @property
    def fraction(self):
        self.__post_init__()
        return Fraction(self.numerator, self.denominator)

    @property
    def seconds(self):
        self.__post_init__()
        return self.numerator / self.denominator


@dataclass(frozen=True, slots=True)
class DyadicDuration:
    numerator_seconds: int
    subdivision_level: int

    def __post_init__(self):
        if type(self.numerator_seconds) is not int or type(self.subdivision_level) is not int:
            raise TypeError("dyadic duration requires exact integers")
        if not 0 < self.numerator_seconds <= MAX_ACTION_SECONDS:
            raise ValueError("physical duration exceeds the admitted positive range")
        if not 0 <= self.subdivision_level <= MAX_SUBDIVISION_LEVEL:
            raise ValueError("subdivision level exceeds the resource limit; no convergence claim")

    @property
    def seconds(self):
        return self.numerator_seconds / (1 << self.subdivision_level)


def checked_duration(duration):
    if type(duration) not in (DyadicDuration, RationalSeconds):
        raise TypeError("duration must be an exact DyadicDuration or RationalSeconds")
    duration.__post_init__()
    if duration.seconds <= 0:
        raise ValueError("physical duration must be strictly positive")
    return duration.seconds


def validate_substep_seconds(seconds, duration):
    if type(seconds) is not float or seconds != checked_duration(duration):
        raise ValueError("substep seconds must equal the duration's binary64 conversion")


@dataclass(frozen=True, slots=True)
class IntegrationPolicy:
    subdivision_level: int
    method: str = "coupled-euler-midpoint-ageing-v1"

    def __post_init__(self):
        DyadicDuration(1, self.subdivision_level)
        if type(self.method) is not str or self.method != "coupled-euler-midpoint-ageing-v1":
            raise ValueError("unsupported integration method")

    def duration(self, physical_seconds):
        self.__post_init__()
        return DyadicDuration(physical_seconds, self.subdivision_level)

    @property
    def substeps(self):
        self.__post_init__()
        return 1 << self.subdivision_level


__all__ = ["DyadicDuration", "IntegrationPolicy"]
