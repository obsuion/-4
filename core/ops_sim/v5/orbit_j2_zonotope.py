"""Opt-in, original-anchor centered-zonotope endpoint enclosure, method v1.

This module leaves F1/F2/F3 and all dispatch/persistence owners unchanged.
It encloses the real F1 field, not derivatives of its rounded force program.
The private generator state is diagnostic data, never restart authority.
See M2_J2_ZONOTOPE.md for the inclusion argument and work/allocation contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import (
    Context, Decimal, DecimalException, DivisionByZero, InvalidOperation,
    Overflow, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Subnormal, Underflow,
)
from fractions import Fraction
from math import isfinite, nextafter

from . import orbit_j2 as _coast
from . import orbit_j2_enclosure as _old
from .frames import CartesianState
from .orbit_config import (FrameDefinition, GeometryInstant, ReferenceEllipsoid,
                           UniformRotationDefinition, _exact, _instant)
from .parameters import ScalarParameter
from .provenance import ParameterProvenance
from .ids import ParameterId, SourceRecordId


_I = _old._I
_Unresolved = _old._Unresolved
# A module-local dependency seam; changing this in a test never modifies F2.
_nominal_evaluator = _coast.evaluate_j2_cartesian_state
METHOD_ID = "m2-centered-zonotope-pb6-v1"
_RANK_BITS = 4096
_DIMENSION = 6
_MAX_GENERATORS = 12
_PB_ORDER = 6
# Explicit conservative control/conversion reservations. Context operations,
# guarded Decimal endpoint operations and rational operations are ADDITIONAL
# executed leaves, not included a second time in these schedules.
_ADMISSION_RESERVATION = 512
_TUBE_CONTROL_RESERVATION = 256 + 2048 * 16
_CENTER_CONTROL_RESERVATION = 16384
_NEW_STEP_CONTROL_RESERVATION = 8192
_FINAL_CONTROL_RESERVATION = 256
_CONTEXT_ARITIES = {"add": 2, "subtract": 2, "multiply": 2, "divide": 2,
                    "sqrt": 1, "next_minus": 1, "next_plus": 1}


@dataclass(frozen=True, slots=True)
class J2ZonotopePolicy:
    """Strict numerical policy, separate from the legacy box policy.

    Primitive units bound protected arithmetic; they are not seconds or RSS.
    Zero-span and rejected queries still account their admission work.
    """

    base_policy: _old.J2EnclosurePolicy
    scale_exponents: tuple[int, int, int, int, int, int]
    max_scalar_operations: int
    method_id: str = field(init=False, default=METHOD_ID)
    method_version: int = field(init=False, default=1)
    pb_order: int = field(init=False, default=_PB_ORDER)
    max_generators: int = field(init=False, default=_MAX_GENERATORS)
    retained_generators: int = field(init=False, default=6)
    rank_bit_cap: int = field(init=False, default=_RANK_BITS)

    def __post_init__(self) -> None:
        _exact(self.base_policy, _old.J2EnclosurePolicy, "base_policy")
        p = self.base_policy
        p = _old.J2EnclosurePolicy(p.step_seconds, p.max_steps, p.min_radius_m,
                                  p.precision_digits, p.max_picard_iterations)
        _exact(self.scale_exponents, tuple, "scale_exponents")
        if len(self.scale_exponents) != 6:
            raise ValueError("scale_exponents must have six entries")
        for exponent in self.scale_exponents:
            _exact(exponent, int, "scale exponent")
            if not -32 <= exponent <= 32:
                raise ValueError("scale exponents must be in [-32, 32]")
        _exact(self.max_scalar_operations, int, "max_scalar_operations")
        if not 1 <= self.max_scalar_operations <= 2**24:
            raise ValueError("max_scalar_operations must be in [1, 2**24]")
        object.__setattr__(self, "base_policy", p)


@dataclass(frozen=True, slots=True)
class J2ZonotopePolicyV2(J2ZonotopePolicy):
    """Explicit resource v2; the PB6 method and all-set numerical policy stay v1."""

    resource_policy_version: int = field(init=False, default=2)

    def __post_init__(self) -> None:
        _exact(self.base_policy, _old.J2EnclosurePolicy, "base_policy")
        p = self.base_policy
        p = _old.J2EnclosurePolicy(p.step_seconds, p.max_steps, p.min_radius_m,
                                  p.precision_digits, p.max_picard_iterations)
        _exact(self.scale_exponents, tuple, "scale_exponents")
        if len(self.scale_exponents) != 6:
            raise ValueError("scale_exponents must have six entries")
        for exponent in self.scale_exponents:
            _exact(exponent, int, "scale exponent")
            if not -32 <= exponent <= 32:
                raise ValueError("scale exponents must be in [-32, 32]")
        _exact(self.max_scalar_operations, int, "max_scalar_operations")
        if not 1 <= self.max_scalar_operations <= 2**31:
            raise ValueError("max_scalar_operations must be in [1, 2**31]")
        object.__setattr__(self, "base_policy", p)



class _D(Decimal):
    """Query-owned endpoint: legacy comparisons/copies cannot go uncharged.

    Decimal context arithmetic remains in _Context. This class deliberately
    does not implement general numeric operators: all arithmetic uses explicit
    contexts or exact rational helpers. Plain Decimal constants in the old
    helpers are covered by the separate finite control/conversion schedules.
    """

    def __new__(cls, value, ar):
        obj = Decimal.__new__(cls, value)
        obj._ar = ar
        return obj

    def _compare(self, other, method):
        self._ar.charge()
        if isinstance(other, _D) and other._ar is not self._ar:
            raise _Unresolved("mixed query arithmetic endpoints")
        return method(self, other)

    def __lt__(self, other):
        return self._compare(other, Decimal.__lt__)

    def __le__(self, other):
        return self._compare(other, Decimal.__le__)

    def __gt__(self, other):
        return self._compare(other, Decimal.__gt__)

    def __ge__(self, other):
        return self._compare(other, Decimal.__ge__)

    def __eq__(self, other):
        return self._compare(other, Decimal.__eq__)

    def __ne__(self, other):
        return self._compare(other, Decimal.__ne__)

    __hash__ = Decimal.__hash__

    def _implicit_arithmetic(self, *args):
        # An added/future helper must choose an explicit accounted context.
        # Reject before Decimal can consult ambient context or perform work.
        raise _Unresolved("implicit Decimal arithmetic is not accounted")

    __add__ = __radd__ = __sub__ = __rsub__ = _implicit_arithmetic
    __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _implicit_arithmetic
    __floordiv__ = __rfloordiv__ = __mod__ = __rmod__ = _implicit_arithmetic
    __divmod__ = __rdivmod__ = _implicit_arithmetic
    __pow__ = __rpow__ = __neg__ = __pos__ = __abs__ = _implicit_arithmetic

    def copy_abs(self, context=None):
        self._ar.charge()
        return self._ar.wrap(Decimal.copy_abs(self))

    def copy_negate(self, context=None):
        self._ar.charge()
        return self._ar.wrap(Decimal.copy_negate(self))

    def as_integer_ratio(self):
        _decimal_rank_admission(self, self._ar)
        self._ar.charge()
        result = Decimal.as_integer_ratio(self)
        self._ar.charge()
        _check_fraction_bits(Fraction(*result), self._ar)
        return result


class _Context:
    """Only the explicitly admitted context methods are exposed/charged."""

    def __init__(self, context: Context, ar):
        self._context = context
        self._ar = ar

    def _call(self, name, *args):
        if (type(name) is not str or name not in _CONTEXT_ARITIES or
                len(args) != _CONTEXT_ARITIES[name]):
            raise _Unresolved("missing context-operation accounting path")
        # Charge the actual context operation and every scalar input conversion
        # before performing any protected conversion/context work.
        self._ar.charge(1 + len(args))
        values = []
        for value in args:
            if isinstance(value, _D) and value._ar is not self._ar:
                raise _Unresolved("mixed query arithmetic endpoints")
            values.append(Decimal(value))
        result = getattr(self._context, name)(*values)
        return self._ar.wrap(result)

    def add(self, a, b):
        return self._call("add", a, b)

    def subtract(self, a, b):
        return self._call("subtract", a, b)

    def multiply(self, a, b):
        return self._call("multiply", a, b)

    def divide(self, a, b):
        return self._call("divide", a, b)

    def sqrt(self, a):
        return self._call("sqrt", a)

    def next_minus(self, a):
        return self._call("next_minus", a)

    def next_plus(self, a):
        return self._call("next_plus", a)


class _Arithmetic:
    """All numeric proof work is per-query and charged before execution.

    operations = leaf_operations + reserved_units. The latter is an explicitly
    conservative allocation/control schedule, not an observed leaf count.
    A rejected counter admits no subsequent protected operation.
    """

    def __init__(self, precision: int, max_scalar_operations: int = 2**24):
        _exact(precision, int, "precision")
        _exact(max_scalar_operations, int, "max_scalar_operations")
        if not 40 <= precision <= 80 or not 1 <= max_scalar_operations <= 2**24:
            raise ValueError("arithmetic precision/work outside method domain")
        self.limit = max_scalar_operations
        self.operations = 0
        self.leaf_operations = 0
        self.reserved_units = 0
        self.rejected = False
        self.picard_attempts = 0
        self.attempted_steps = 0
        self.completed_steps = 0
        self.reductions = 0
        traps = [InvalidOperation, DivisionByZero, Overflow, Underflow, Subnormal]
        settings = dict(prec=precision, Emin=-200, Emax=200, traps=traps,
                        clamp=0, capitals=1)
        self.down = _Context(Context(rounding=ROUND_FLOOR, **settings), self)
        self.up = _Context(Context(rounding=ROUND_CEILING, **settings), self)
        self.nearest = _Context(Context(rounding=ROUND_HALF_EVEN, **settings), self)

    def _admit(self, count):
        if self.rejected:
            raise _Unresolved("primitive work ceiling already rejected")
        if type(count) is not int or count < 0:
            raise _Unresolved("missing or invalid operation charge")
        if count > self.limit - self.operations:
            self.rejected = True
            raise _Unresolved("primitive scalar-operation work exhausted")
        self.operations += count

    def charge(self, count=1):
        self._admit(count)
        self.leaf_operations += count

    def reserve(self, count, label):
        if type(label) is not str or not label:
            raise _Unresolved("unidentified composite work reservation")
        self._admit(count)
        self.reserved_units += count

    def wrap(self, value):
        self.charge(2)  # finite validation and exact Decimal endpoint conversion
        if not value.is_finite():
            raise _Unresolved("nonfinite Decimal endpoint")
        return _D(value, self)

    def point(self, value):
        self.charge()  # exact scalar conversion, independent of ambient context
        if type(value) is float:
            d = Decimal.from_float(value)
        elif type(value) is int or type(value) is Decimal:
            d = Decimal(value)
        elif isinstance(value, _D) and value._ar is self:
            d = Decimal(value)
        else:
            raise _Unresolved("unsupported exact scalar conversion")
        d = self.wrap(d)
        return _I(d, d)

    def add(self, a, b):
        return _I(self.down.add(a.lo, b.lo), self.up.add(a.hi, b.hi))

    def neg(self, a):
        # Normalize raw endpoints introduced by the unchanged tube helper.
        return _I(self.point(a.hi).lo.copy_negate(),
                  self.point(a.lo).lo.copy_negate())

    def sub(self, a, b):
        return self.add(a, self.neg(b))

    def mul(self, a, b):
        pairs = ((a.lo, b.lo), (a.lo, b.hi), (a.hi, b.lo), (a.hi, b.hi))
        lower = tuple(self.down.multiply(x, y) for x, y in pairs)
        upper = tuple(self.up.multiply(x, y) for x, y in pairs)
        return _I(min(lower), max(upper))

    def div(self, a, b):
        denominator = _I(self.point(b.lo).lo, self.point(b.hi).hi)
        if denominator.lo <= 0 <= denominator.hi:
            raise _Unresolved("interval division contains zero")
        reciprocal = _I(self.down.divide(Decimal(1), denominator.hi),
                        self.up.divide(Decimal(1), denominator.lo))
        return self.mul(a, reciprocal)

    def square(self, a):
        a = _I(self.point(a.lo).lo, self.point(a.hi).hi)
        upper = max(self.up.multiply(x, x) for x in (a.lo, a.hi))
        lower = (self.point(0).lo if a.lo <= 0 <= a.hi else
                 min(self.down.multiply(x, x) for x in (a.lo, a.hi)))
        return _I(lower, upper)

    def sqrt(self, a):
        a = _I(self.point(a.lo).lo, self.point(a.hi).hi)
        if a.lo <= 0:
            raise _Unresolved("radius interval does not exclude zero")
        lo = self.down.next_minus(self.down.sqrt(a.lo))
        hi = self.up.next_plus(self.up.sqrt(a.hi))
        if lo <= 0:
            raise _Unresolved("square-root arithmetic bracket failed")
        low_square = _rmul(_fraction(lo, self), _fraction(lo, self), self)
        high_square = _rmul(_fraction(hi, self), _fraction(hi, self), self)
        if (_rcompare(low_square, _fraction(a.lo, self), self) > 0 or
                _rcompare(high_square, _fraction(a.hi, self), self) < 0):
            raise _Unresolved("square-root arithmetic bracket failed")
        return _I(lo, hi)

    def total(self, values):
        result = self.point(0)
        for value in values:
            result = self.add(result, value)
        return result


class _ArithmeticV2(_Arithmetic):
    """Closed v2 bootstrap: one ledger, no ceiling injection or later top-up."""

    def __init__(self, precision: int, max_scalar_operations: int = 2**31):
        _exact(precision, int, "precision")
        _exact(max_scalar_operations, int, "max_scalar_operations")
        if not 40 <= precision <= 80 or not 1 <= max_scalar_operations <= 2**31:
            raise ValueError("arithmetic precision/work outside method domain")
        self.limit = max_scalar_operations
        self.operations = 0
        self.leaf_operations = 0
        self.reserved_units = 0
        self.rejected = False
        self.picard_attempts = 0
        self.attempted_steps = 0
        self.completed_steps = 0
        self.reductions = 0
        traps = [InvalidOperation, DivisionByZero, Overflow, Underflow, Subnormal]
        settings = dict(prec=precision, Emin=-200, Emax=200, traps=traps,
                        clamp=0, capitals=1)
        self.down = _Context(Context(rounding=ROUND_FLOOR, **settings), self)
        self.up = _Context(Context(rounding=ROUND_CEILING, **settings), self)
        self.nearest = _Context(Context(rounding=ROUND_HALF_EVEN, **settings), self)



def _check_fraction_bits(value, ar):
    ar.charge(4)  # numerator/denominator bit extraction and both comparisons
    if (value.numerator.bit_length() > _RANK_BITS or
            value.denominator.bit_length() > _RANK_BITS):
        raise _Unresolved("rank rational intermediate exceeds 4096 bits")


def _decimal_rank_admission(value, ar):
    ar.charge(8)  # tuple extraction, finite/length/sign/exponent/bound checks
    if not value.is_finite():
        raise _Unresolved("nonfinite rank operand")
    _, digits, exponent = value.as_tuple()
    # log2(10)<4: a conservative pre-conversion bound on either integer.
    if 4 * (len(digits) + abs(exponent) + 1) > _RANK_BITS:
        raise _Unresolved("rank rational conversion exceeds 4096-bit bound")


def _fraction(value, ar):
    if type(value) is Fraction:
        _check_fraction_bits(value, ar)
        return value
    if type(value) is int:
        ar.charge()
        result = Fraction(value)
    elif type(value) is Decimal or isinstance(value, _D):
        _decimal_rank_admission(value, ar)
        ar.charge()
        # Decimal's exact integer-ratio conversion; the bound was checked first.
        numerator, denominator = Decimal.as_integer_ratio(value)
        ar.charge()
        result = Fraction(numerator, denominator)
    elif type(value) is float:
        ar.charge(2)
        result = Fraction(value)
    else:
        raise _Unresolved("unsupported rational conversion")
    _check_fraction_bits(result, ar)
    return result


def _rprecheck(a, b, ar, addition=False):
    _check_fraction_bits(a, ar)
    _check_fraction_bits(b, ar)
    ar.charge(8)  # integer bound sums, bit lengths and admission comparisons
    if addition:
        numerator_bits = max(a.numerator.bit_length() + b.denominator.bit_length(),
                             b.numerator.bit_length() + a.denominator.bit_length()) + 1
    else:
        numerator_bits = a.numerator.bit_length() + b.numerator.bit_length()
    denominator_bits = a.denominator.bit_length() + b.denominator.bit_length()
    if max(numerator_bits, denominator_bits) > _RANK_BITS:
        raise _Unresolved("rank rational intermediate exceeds 4096-bit bound")


def _radd(a, b, ar):
    _rprecheck(a, b, ar, addition=True)
    ar.charge()
    result = a + b
    _check_fraction_bits(result, ar)
    return result


def _rmul(a, b, ar):
    _rprecheck(a, b, ar)
    ar.charge()
    result = a * b
    _check_fraction_bits(result, ar)
    return result


def _rcompare(a, b, ar):
    # Cross products are bounded before Fraction comparison performs them.
    _check_fraction_bits(a, ar)
    _check_fraction_bits(b, ar)
    ar.charge(8)
    if max(a.numerator.bit_length() + b.denominator.bit_length(),
           b.numerator.bit_length() + a.denominator.bit_length()) > _RANK_BITS:
        raise _Unresolved("rank rational comparison exceeds 4096-bit bound")
    ar.charge(4)
    return (a > b) - (a < b)


def _shift(value, exponent, ar):
    """Exact Decimal tuple exponent shift: no ambient arithmetic/division."""
    ar.charge(5)  # finite check, tuple, exponent sum, construction, wrapping
    if not value.is_finite() or type(exponent) is not int:
        raise _Unresolved("invalid exact decimal scaling")
    sign, digits, old_exponent = value.as_tuple()
    result = Decimal((sign, digits, old_exponent + exponent))
    return ar.wrap(result)


def _midpoint(a, ar):
    return ar.nearest.divide(ar.nearest.add(a.lo, a.hi), Decimal(2))


def _radius(a, ar):
    return max(ar.point(a.lo).lo.copy_abs(), ar.point(a.hi).hi.copy_abs())


@dataclass(frozen=True, slots=True)
class _Zonotope:
    center: tuple[Decimal, ...]
    generators: tuple[tuple[Decimal, ...], ...]
    births: tuple[int, ...]
    time: Fraction

    def __post_init__(self):
        if (type(self.center) is not tuple or len(self.center) != 6 or
                type(self.generators) is not tuple or len(self.generators) > 18 or
                type(self.births) is not tuple or len(self.births) != len(self.generators) or
                type(self.time) is not Fraction):
            raise ValueError("invalid private centered set shape")
        if any(not isinstance(x, Decimal) or not x.is_finite() for x in self.center):
            raise ValueError("private center must contain finite Decimal values")
        for column in self.generators:
            if type(column) is not tuple or len(column) != 6:
                raise ValueError("private generators must be six-component columns")
            if any(not isinstance(x, Decimal) or not x.is_finite() for x in column):
                raise ValueError("private generators must contain finite Decimal values")
        if any(type(x) is not int or x < 0 or x > 2**20 for x in self.births):
            raise ValueError("private generator birth outside bounded domain")
        if len(set(self.births)) != len(self.births):
            raise ValueError("private generator births must be unique")


def _initial_set(components, scale_exponents, ar, time=Fraction(0)):
    ar.reserve(128, "initial set allocation/control")
    if len(components) != 6 or len(scale_exponents) != 6:
        raise _Unresolved("six components/scales required")
    center = tuple(_shift(ar.point(value).lo, -exponent, ar)
                   for value, exponent in zip(components, scale_exponents))
    return _Zonotope(center, (), (), time)


def _project_box(z, scale_exponents, ar):
    ar.reserve(256, "six-coordinate projection allocation/control")
    if len(z.generators) > 12:
        raise _Unresolved("unreduced set exceeds twelve generators")
    result = []
    for axis in range(6):
        center = ar.point(z.center[axis]).lo
        if not z.generators:
            value = _shift(center, scale_exponents[axis], ar)
            result.append(_I(value, value))
            continue
        radius = ar.point(0).lo
        for column in z.generators:
            radius = ar.up.add(radius, ar.point(column[axis]).lo.copy_abs())
        lo = ar.down.subtract(center, radius)
        hi = ar.up.add(center, radius)
        result.append(_I(_shift(lo, scale_exponents[axis], ar),
                         _shift(hi, scale_exponents[axis], ar)))
    return tuple(result)


def _jacobian_box(tube, model, scale_exponents, ar):
    """Analytic derivative of the real F1 field on the WHOLE physical tube."""
    ar.reserve(1024, "analytic Jacobian fixed-loop control/allocation")
    x = tuple(tube[:3])
    q = ar.total(ar.square(a) for a in x)
    if q.lo <= 0:
        raise _Unresolved("Jacobian requires strictly positive squared radius")
    b = ar.div(ar.point(1), ar.sqrt(q))
    b2 = ar.square(b)
    b3 = ar.mul(b2, b)
    b5 = ar.mul(b3, b2)
    b7 = ar.mul(b5, b2)
    b9 = ar.mul(b7, b2)
    mu = ar.point(model.gravitational_parameter_m3_s2.value)
    beta = ar.mul(ar.point(1.5), ar.mul(mu, ar.mul(ar.point(model.j2.value),
                  ar.square(ar.point(model.reference_radius_m.value)))))
    z2 = ar.square(x[2])
    zero = ar.point(0)
    matrix = [[zero for _ in range(6)] for _ in range(6)]
    for i in range(3):
        matrix[i][i + 3] = ar.point(1)
        kappa = ar.point(3 if i == 2 else 1)
        fi = ar.sub(ar.mul(ar.point(5), ar.mul(z2, b7)), ar.mul(kappa, b5))
        for j in range(3):
            first = ar.mul(ar.point(3), ar.mul(mu, ar.mul(x[i], ar.mul(x[j], b5))))
            if i == j:
                first = ar.sub(first, ar.mul(mu, b3))
            derivative = ar.sub(zero, ar.mul(ar.point(35),
                                ar.mul(z2, ar.mul(x[j], b9))))
            if j == 2:
                derivative = ar.add(derivative, ar.mul(ar.point(10), ar.mul(x[2], b7)))
            derivative = ar.add(derivative, ar.mul(ar.point(5),
                                 ar.mul(kappa, ar.mul(x[j], b7))))
            correction = ar.mul(x[i], derivative)
            if i == j:
                correction = ar.add(correction, fi)
            matrix[i + 3][j] = ar.add(first, ar.mul(beta, correction))
    # Every block is scaled; upper-right entries are D_v / D_r, not always 1.
    return tuple(tuple(_I(_shift(a.lo, scale_exponents[j] - scale_exponents[i], ar),
                          _shift(a.hi, scale_exponents[j] - scale_exponents[i], ar))
                       for j, a in enumerate(row)) for i, row in enumerate(matrix))


def _matrix_product(a, b, ar):
    ar.reserve(512, "six-by-six matrix fixed-loop control/allocation")
    return tuple(tuple(ar.total(ar.mul(a[i][k], b[k][j]) for k in range(6))
                       for j in range(6)) for i in range(6))


def _flow_derivative_box(jacobian, h, ar):
    """PB6 enclosure of all time-ordered products, including signed time."""
    ar.reserve(1024, "PB6 fixed-loop control/allocation")
    h = _I(ar.point(h.lo).lo, ar.point(h.hi).hi)
    norm = ar.point(0).lo
    for row in jacobian:
        row_sum = ar.point(0).lo
        for entry in row:
            row_sum = ar.up.add(row_sum, _radius(entry, ar))
        norm = max(norm, row_sum)
    z = ar.up.multiply(_radius(h, ar), norm)
    if not z < 8:
        raise _Unresolved("PB6 tail requires a proved z < 8")
    denominator_factor = ar.down.subtract(Decimal(1), ar.up.divide(z, Decimal(8)))
    if not denominator_factor > 0:
        raise _Unresolved("PB6 tail denominator not proved positive")
    numerator = ar.point(1).lo
    for _ in range(7):
        numerator = ar.up.multiply(numerator, z)
    denominator = ar.down.multiply(Decimal(5040), denominator_factor)
    tail = ar.up.divide(numerator, denominator)
    one, zero = ar.point(1), ar.point(0)
    result = [[one if i == j else zero for j in range(6)] for i in range(6)]
    power = jacobian
    hpower = one
    factorial = 1
    for order in range(1, 7):
        hpower = ar.mul(hpower, h)
        ar.charge()  # bounded exact factorial update
        factorial *= order
        factor = ar.div(hpower, ar.point(factorial))
        for i in range(6):
            for j in range(6):
                result[i][j] = ar.add(result[i][j], ar.mul(factor, power[i][j]))
        if order < 6:
            power = _matrix_product(power, jacobian, ar)
    remainder = _I(tail.copy_negate(), tail)
    return tuple(tuple(ar.add(entry, remainder) for entry in row) for row in result)


def _reduce_generators(z, ar, step_index=0):
    """Keep six exact-rank columns, enclose all discarded columns by axes."""
    ar.reserve(2048, "bounded eighteen-column rank/reduction control/allocation")
    columns = []
    births = []
    for column, birth in zip(z.generators, z.births):
        if any(ar.point(value).lo != 0 for value in column):
            columns.append(tuple(ar.point(value).lo for value in column))
            births.append(birth)
    if len(columns) <= 12:
        return _Zonotope(z.center, tuple(columns), tuple(births), z.time)
    scores = []
    for column in columns:
        score = _fraction(0, ar)
        for value in column:
            exact = _fraction(value, ar)
            score = _radd(score, _rmul(exact, exact, ar), ar)
        scores.append(score)
    remaining = list(range(len(columns)))
    kept = []
    for _ in range(6):
        best = remaining[0]
        for index in remaining[1:]:
            comparison = _rcompare(scores[index], scores[best], ar)
            ar.charge()  # stable bounded birth-ID comparison
            if comparison > 0 or (comparison == 0 and births[index] < births[best]):
                best = index
        remaining.remove(best)
        kept.append(best)
    new_columns = [columns[index] for index in kept]
    new_births = [births[index] for index in kept]
    # IDs for fresh axes are distinct from error births and inherited columns.
    for axis in range(6):
        radius = ar.point(0).lo
        for index in remaining:
            radius = ar.up.add(radius, columns[index][axis].copy_abs())
        if radius != 0:
            column = tuple(radius if j == axis else ar.point(0).lo for j in range(6))
            new_columns.append(column)
            ar.charge(3)
            birth = step_index * 32 + 16 + axis
            if birth in new_births:
                raise _Unresolved("generator birth identity collision")
            new_births.append(birth)
    ar.reductions += 1
    return _Zonotope(z.center, tuple(new_columns), tuple(new_births), z.time)


def _transport_generators(z, center_intervals_scaled, matrix, ar, step_index=0):
    """Mean-value transport with independently enclosing all three residuals."""
    ar.reserve(2048, "bounded transport residual control/allocation")
    center = tuple(_midpoint(a, ar) for a in center_intervals_scaled)
    center_error = tuple(ar.sub(a, ar.point(c))
                         for a, c in zip(center_intervals_scaled, center))
    cmat = tuple(tuple(_midpoint(a, ar) for a in row) for row in matrix)
    delta = tuple(tuple(ar.sub(a, ar.point(c)) for a, c in zip(row, crow))
                  for row, crow in zip(matrix, cmat))
    columns = []
    errors = [_radius(a, ar) for a in center_error]
    for column in z.generators:
        rounded = []
        for i in range(6):
            value = ar.point(0).lo
            for k in range(6):
                value = ar.nearest.add(value, ar.nearest.multiply(cmat[i][k], column[k]))
            rounded.append(value)
            exact_cg = ar.total(ar.mul(ar.point(cmat[i][k]), ar.point(column[k]))
                                for k in range(6))
            rounding = ar.sub(exact_cg, ar.point(value))
            matrix_error = ar.total(ar.mul(delta[i][k], ar.point(column[k])) for k in range(6))
            errors[i] = ar.up.add(errors[i], _radius(rounding, ar))
            errors[i] = ar.up.add(errors[i], _radius(matrix_error, ar))
        columns.append(tuple(rounded))
    births = list(z.births)
    for axis, radius in enumerate(errors):
        if radius != 0:
            columns.append(tuple(radius if j == axis else ar.point(0).lo for j in range(6)))
            ar.charge(3)
            birth = step_index * 32 + axis
            if birth in births:
                raise _Unresolved("generator birth identity collision")
            births.append(birth)
    trial = _Zonotope(center, tuple(columns), tuple(births), z.time)
    return _reduce_generators(trial, ar, step_index)


def _transport_step(z, h, model, policy, ar, step_index=0, next_time=None):
    """One all-set step; return its complete SI Picard tube, not samples."""
    ar.reserve(_NEW_STEP_CONTROL_RESERVATION, "new step bounded control/allocation")
    ar.attempted_steps += 1
    p, scales = policy.base_policy, policy.scale_exponents
    box = _project_box(z, scales, ar)
    ar.reserve(_TUBE_CONTROL_RESERVATION, "unchanged tube bounded legacy control/conversions")
    tube, _ = _old._tube(box, h, model, p, ar)
    center_box = tuple(_I(_shift(c, scale, ar), _shift(c, scale, ar))
                       for c, scale in zip(z.center, scales))
    ar.reserve(_CENTER_CONTROL_RESERVATION, "unchanged center coefficients legacy control/conversions")
    polynomial = _old._coefficients(center_box, 6, model, ar)
    remainder = _old._coefficients(tube, 7, model, ar)
    yc = []
    for axis, (coefficients, derivatives) in enumerate(zip(polynomial, remainder)):
        value = derivatives[7]
        for order in range(6, -1, -1):
            value = ar.add(coefficients[order], ar.mul(h, value))
        yc.append(_I(_shift(value.lo, -scales[axis], ar),
                     _shift(value.hi, -scales[axis], ar)))
    jacobian = _jacobian_box(tube, model, scales, ar)
    matrix = _flow_derivative_box(jacobian, h, ar)
    candidate = _transport_generators(z, yc, matrix, ar, step_index)
    if next_time is None:
        # Private test convenience: only a point duration has exact time authority.
        if ar.point(h.lo).lo != ar.point(h.hi).hi:
            raise _Unresolved("next_time required for interval duration")
        next_time = _radd(z.time, _fraction(h.lo, ar), ar)
    _check_fraction_bits(next_time, ar)
    candidate = _Zonotope(candidate.center, candidate.generators, candidate.births, next_time)
    final_box = _project_box(candidate, scales, ar)
    ar.reserve(128, "unchanged endpoint-domain control/conversions")
    _old._domain(final_box, p, ar)
    ar.completed_steps += 1
    return candidate, tuple(tube)


def _upper_float(value, ar):
    """Directed binary64 bound with every conversion/guard precharged."""
    ar.charge(3)
    result = float(value)
    if not isfinite(result):
        raise _Unresolved("error bound exceeds finite binary64")
    represented = ar.point(result).lo
    if represented < value:
        ar.charge(2)
        result = nextafter(result, float("inf"))
    ar.charge()
    if not isfinite(result):
        raise _Unresolved("error bound exceeds finite binary64")
    return result


def _plain(value, ar):
    ar.charge()
    return Decimal(value)


def _plain_set(z, ar):
    ar.reserve(128, "diagnostic immutable-set publication allocation/control")
    return _Zonotope(tuple(_plain(c, ar) for c in z.center),
                     tuple(tuple(_plain(x, ar) for x in column) for column in z.generators),
                     z.births, z.time)


def _reserve_text(value, ar):
    """Reserve legacy UTF8/strip/hash/comparison scans before their execution."""
    ar.charge(2)
    _exact(value, str, "scientific metadata text")
    size = len(value)
    # At most ten scans in the reconstruction chain, including UTF8's at most
    # four bytes per Unicode scalar. The reservation is not an observed count.
    ar.reserve(64 + 40 * size, "metadata text bounded legacy scans")


def _reserve_parameter_metadata(value, ar):
    ar.reserve(256, "parameter metadata bounded structural reconstruction")
    _exact(value, ScalarParameter, "parameter")
    p = value.provenance
    _exact(p, ParameterProvenance, "parameter provenance")
    _exact(p.parameter_id, ParameterId, "parameter_id")
    _reserve_text(p.parameter_id.value, ar)
    _reserve_text(p.units, ar)
    _exact(p.source_ids, tuple, "source_ids")
    ar.charge(4)
    count = len(p.source_ids)
    # Five repeated owner reconstructions are bounded by this envelope; n^2
    # includes worst-case source-ID hash collisions. Charge before iteration.
    ar.reserve(128 * count + 32 * count * count,
               "source-ID reconstruction/hash-collision schedule")
    total_source_characters = 0
    for source in p.source_ids:
        _exact(source, SourceRecordId, "source_id")
        _reserve_text(source.value, ar)
        ar.charge(2)
        total_source_characters += len(source.value)
    ar.charge(2)
    ar.reserve(32 * count * total_source_characters,
               "source-ID hash-collision text-comparison schedule")
    for text in (p.rationale, p.derivation):
        if text is not None:
            _reserve_text(text, ar)


def _reserve_authority_metadata(trajectory, ar):
    """Do not assume existing provenance tuples or strings have bounded size."""
    ar.reserve(512, "two frame graphs and gravity metadata structure")
    initial = trajectory.initial_state
    _exact(initial, CartesianState, "initial_state")
    # Existing owners still perform their full strict reconstruction afterwards.
    for vector in (initial.position, initial.velocity):
        frame = vector.frame
        _exact(frame, FrameDefinition, "frame")
        _exact(frame.ellipsoid, ReferenceEllipsoid, "ellipsoid")
        _exact(frame.rotation, UniformRotationDefinition, "rotation")
        _reserve_text(frame.ellipsoid.name, ar)
        for parameter in (frame.ellipsoid.equatorial_radius_m, frame.ellipsoid.flattening,
                          frame.rotation.initial_phase_rad, frame.rotation.angular_velocity_rad_per_s):
            _reserve_parameter_metadata(parameter, ar)
    model = trajectory.gravity_model
    _exact(model, _coast.J2GravityModel, "gravity_model")
    for parameter in (model.gravitational_parameter_m3_s2, model.j2, model.reference_radius_m):
        _reserve_parameter_metadata(parameter, ar)


def _check_method_identity(policy):
    """Fixed structural ownership checks, before any numerical evaluation."""
    _exact(policy.method_id, str, "method_id")
    _exact(policy.method_version, int, "method_version")
    if policy.method_id != METHOD_ID or policy.method_version != 1:
        raise ValueError("unsupported zonotope algorithm identity")


@dataclass(frozen=True, slots=True)
class J2ZonotopeResult:
    """Original-anchor recomputed enclosure; no mutable/checkpoint authority.

    F2 counts are planned until its unchanged public evaluator returns normally.
    On partial nominal failure its actual partial counts remain None (unknown).
    All success fields remain None after any later proof/publication failure.
    """

    trajectory: _coast.J2CartesianTrajectory
    instant: GeometryInstant
    solver_config: _coast.J2RK4SolverConfig
    policy: J2ZonotopePolicy
    status: str = field(init=False, default="unresolved")
    reason: str | None = field(init=False, default=None)
    nominal_state: CartesianState | None = field(init=False, default=None)
    endpoint_intervals: tuple[tuple[Decimal, Decimal], ...] | None = field(init=False, default=None)
    position_error_bound_m: float | None = field(init=False, default=None)
    velocity_error_bound_m_per_s: float | None = field(init=False, default=None)
    diagnostic_state: _Zonotope | None = field(init=False, default=None)
    attempted_steps: int = field(init=False, default=0)
    completed_steps: int = field(init=False, default=0)
    picard_attempts: int = field(init=False, default=0)
    reductions: int = field(init=False, default=0)
    scalar_operations: int = field(init=False, default=0)
    charged_leaf_operations: int = field(init=False, default=0)
    reserved_control_operations: int = field(init=False, default=0)
    nominal_evaluations: int = field(init=False, default=0)
    planned_nominal_steps: int = field(init=False, default=0)
    planned_nominal_force_calls: int = field(init=False, default=0)
    nominal_completed_steps: int | None = field(init=False, default=None)
    nominal_force_calls: int | None = field(init=False, default=None)
    nominal_counter_provenance: str = field(init=False, default="NOT_RUN")
    method_id: str = field(init=False, default=METHOD_ID)
    method_version: int = field(init=False, default=1)

    __hash__ = None

    def __post_init__(self):
        # Structural/type validation is separate from protected numerical work.
        # Crucially do NOT reconstruct J2CartesianTrajectory here: its constructor
        # evaluates F1. The sole nominal evaluation below owns that admission call.
        _exact(self.trajectory, _coast.J2CartesianTrajectory, "trajectory")
        _exact(self.solver_config, _coast.J2RK4SolverConfig, "solver_config")
        _exact(self.policy, J2ZonotopePolicy, "policy")
        _check_method_identity(self.policy)
        _exact(self.policy.base_policy, _old.J2EnclosurePolicy, "base_policy")
        _exact(self.instant, GeometryInstant, "instant")
        # Only exact bounded ledger bootstrap checks precede its creation.
        ar = _Arithmetic(self.policy.base_policy.precision_digits,
                         self.policy.max_scalar_operations)
        self._execute(ar)

    def _execute(self, ar):
        try:
            self._evaluate(ar)
        except (_Unresolved, DecimalException, OverflowError) as error:
            object.__setattr__(self, "reason", str(error))
        finally:
            for key, value in (("attempted_steps", ar.attempted_steps),
                               ("completed_steps", ar.completed_steps),
                               ("picard_attempts", ar.picard_attempts),
                               ("reductions", ar.reductions),
                               ("scalar_operations", ar.operations),
                               ("charged_leaf_operations", ar.leaf_operations),
                               ("reserved_control_operations", ar.reserved_units)):
                object.__setattr__(self, key, value)

    def _normalized_policy(self):
        return J2ZonotopePolicy(self.policy.base_policy, self.policy.scale_exponents,
                                self.policy.max_scalar_operations)

    def _evaluate(self, ar):
        ar.reserve(_ADMISSION_RESERVATION, "bounded static authority/grid admission")
        policy = self._normalized_policy()
        object.__setattr__(self, "policy", policy)
        t = self.trajectory
        _reserve_authority_metadata(t, ar)
        instant = _instant(self.instant)
        config = _coast.J2RK4SolverConfig(self.solver_config.step_seconds,
                                        self.solver_config.max_steps)
        object.__setattr__(self, "instant", instant)
        object.__setattr__(self, "solver_config", config)
        p = policy.base_policy
        state, model = _coast._authorities(t.initial_state, t.gravity_model)
        # Bind normalized immutable authorities without calling the trajectory
        # constructor's F1 admission. F2 performs that admission exactly once.
        ar.charge(3)
        t = object.__new__(_coast.J2CartesianTrajectory)
        object.__setattr__(t, "initial_state", state)
        object.__setattr__(t, "gravity_model", model)
        object.__setattr__(self, "trajectory", t)
        if state.position.instant.epoch != self.instant.epoch:
            raise ValueError("J2 enclosure requires the same TT reference epoch")
        span = _radd(_fraction(self.instant.elapsed_seconds, ar),
                     _fraction(-state.position.instant.elapsed_seconds, ar), ar)
        ar.charge(8)  # exact absolute/divmod/grid count and bound checks
        nf, nr = divmod(abs(span), _fraction(config.step_seconds, ar))
        full, remainder = divmod(abs(span), _fraction(p.step_seconds, ar))
        if abs(span) > 86400 or nf + bool(nr) > min(config.max_steps, 4096) or full + bool(remainder) > p.max_steps:
            raise _Unresolved("horizon or step work ceiling exceeded before integration")
        try:
            _coast._grid(state.position.instant, self.instant, config)
        except ValueError as error:
            raise _Unresolved(str(error)) from error
        values = (*state.position.components_m, *state.velocity.components_m_per_s,
                  model.gravitational_parameter_m3_s2.value, model.j2.value,
                  model.reference_radius_m.value, config.step_seconds)
        if any(value != 0 and not 1e-100 <= abs(value) <= 1e100 for value in values):
            raise _Unresolved("dynamical input outside F3 arithmetic envelope")
        planned = int(nf + bool(nr))
        object.__setattr__(self, "planned_nominal_steps", planned)
        object.__setattr__(self, "planned_nominal_force_calls", 1 + 4 * planned)
        object.__setattr__(self, "nominal_evaluations", 1)
        object.__setattr__(self, "nominal_counter_provenance", "UNKNOWN_PARTIAL_IF_FAILURE")
        try:
            nominal = _nominal_evaluator(t, self.instant, config)
        except (ValueError, OverflowError) as error:
            raise _Unresolved("F2 nominal arithmetic: " + str(error)) from error
        object.__setattr__(self, "nominal_completed_steps", planned)
        object.__setattr__(self, "nominal_force_calls", 1 + 4 * planned)
        object.__setattr__(self, "nominal_counter_provenance", "DERIVED_FROM_SUCCESSFUL_F2_FIXED_GRID")
        z = _initial_set(values[:6], policy.scale_exponents, ar,
                         _fraction(state.position.instant.elapsed_seconds, ar))
        ar.reserve(128, "unchanged initial-domain control/conversions")
        _old._domain(_project_box(z, policy.scale_exponents, ar), p, ar)
        sign = -1 if span < 0 else 1
        for step in range(full + bool(remainder)):
            ar.charge(4)  # bounded exact signed time-grid construction
            dt = _fraction(p.step_seconds, ar) if step < full else remainder
            signed = _rmul(_fraction(sign, ar), dt, ar)
            h = ar.div(ar.point(signed.numerator), ar.point(signed.denominator))
            time = _radd(z.time, signed, ar)
            z, _ = _transport_step(z, h, model, policy, ar, step, time)
        ar.reserve(_FINAL_CONTROL_RESERVATION, "final distance/publication control/allocation")
        box = _project_box(z, policy.scale_exponents, ar)
        components = (*nominal.position.components_m, *nominal.velocity.components_m_per_s)
        radii = tuple(_radius(ar.sub(a, ar.point(value)), ar)
                      for a, value in zip(box, components))
        position = _upper_float(max(radii[:3]), ar)
        velocity = _upper_float(max(radii[3:]), ar)
        endpoints = tuple((_plain(a.lo, ar), _plain(a.hi, ar)) for a in box)
        diagnostic = _plain_set(z, ar)
        # All numeric and allocation checks have passed: publish together.
        for key, value in (("nominal_state", nominal), ("endpoint_intervals", endpoints),
                           ("position_error_bound_m", position),
                           ("velocity_error_bound_m_per_s", velocity),
                           ("diagnostic_state", diagnostic), ("status", "enclosed")):
            object.__setattr__(self, key, value)


@dataclass(frozen=True, slots=True)
class J2ZonotopeResultV2(J2ZonotopeResult):
    """Distinct resource-bound record; inherited numerical publication is atomic."""

    policy: J2ZonotopePolicyV2
    resource_policy_version: int = field(init=False, default=2)

    __hash__ = None

    def __post_init__(self):
        # Structural/type validation is separate from protected numerical work.
        # Crucially do NOT reconstruct J2CartesianTrajectory here: its constructor
        # evaluates F1. The sole nominal evaluation below owns that admission call.
        _exact(self.trajectory, _coast.J2CartesianTrajectory, "trajectory")
        _exact(self.solver_config, _coast.J2RK4SolverConfig, "solver_config")
        _exact(self.policy, J2ZonotopePolicyV2, "policy")
        _check_method_identity(self.policy)
        _exact(self.policy.resource_policy_version, int, "resource_policy_version")
        if self.policy.resource_policy_version != 2:
            raise ValueError("unsupported zonotope resource policy version")
        _exact(self.policy.base_policy, _old.J2EnclosurePolicy, "base_policy")
        _exact(self.instant, GeometryInstant, "instant")
        # Only exact bounded ledger bootstrap checks precede its creation.
        ar = _ArithmeticV2(self.policy.base_policy.precision_digits,
                         self.policy.max_scalar_operations)
        self._execute(ar)

    def _normalized_policy(self):
        return J2ZonotopePolicyV2(self.policy.base_policy, self.policy.scale_exponents,
                                  self.policy.max_scalar_operations)


def evaluate_j2_zonotope_enclosure(trajectory, instant, solver_config, policy) -> J2ZonotopeResult:
    return J2ZonotopeResult(trajectory, instant, solver_config, policy)


def evaluate_j2_zonotope_enclosure_v2(trajectory, instant, solver_config, policy) -> J2ZonotopeResultV2:
    return J2ZonotopeResultV2(trajectory, instant, solver_config, policy)


__all__ = ["J2ZonotopePolicy", "J2ZonotopeResult", "evaluate_j2_zonotope_enclosure",
           "J2ZonotopePolicyV2", "J2ZonotopeResultV2", "evaluate_j2_zonotope_enclosure_v2"]


from .provenance import SensitivityRange as _CoefficientSensitivityRange


class _CoefficientArithmeticV3(_Arithmetic):
    """Closed private ledger for one incremental coefficient invocation.

    This identity does not select an endpoint method or publish a v3 result.
    Primitive charging/rounding guards are inherited without alteration; the
    new kernel has its own control/workspace schedule and exhaustion prefix.
    """

    def __init__(self, precision: int, max_scalar_operations: int = 2**31):
        _exact(precision, int, "precision")
        _exact(max_scalar_operations, int, "max_scalar_operations")
        if not 40 <= precision <= 80 or not 1 <= max_scalar_operations <= 2**31:
            raise ValueError("coefficient precision/work outside kernel domain")
        self.kernel_id = "incremental-j2-jet-v1"
        self.resource_policy_version = 3
        self.precision_digits = precision
        self.limit = max_scalar_operations
        self.operations = 0
        self.leaf_operations = 0
        self.reserved_units = 0
        self.rejected = False
        self.picard_attempts = 0
        self.attempted_steps = 0
        self.completed_steps = 0
        self.reductions = 0
        traps = [InvalidOperation, DivisionByZero, Overflow, Underflow, Subnormal]
        settings = dict(prec=precision, Emin=-200, Emax=200, traps=traps,
                        clamp=0, capitals=1)
        self.down = _Context(Context(rounding=ROUND_FLOOR, **settings), self)
        self.up = _Context(Context(rounding=ROUND_CEILING, **settings), self)
        self.nearest = _Context(Context(rounding=ROUND_HALF_EVEN, **settings), self)


def _coefficients_incremental_v1(box, order, model, ar):
    """Extend invocation-local J2 jets, preserving legacy successful values.

    Return six complete SI Taylor coefficient lists, or raise without publishing
    a partial result. Orders six and seven are the entire admitted domain.
    Every lower jet coefficient is fixed before its next degree is appended.
    This function neither replaces the old kernel nor evaluates an endpoint.
    """
    # Only this bounded closed-bootstrap check precedes ledger admission. No
    # caller interval, model constructor, native context or rational arithmetic
    # is consulted until a compatible exact ledger has been established.
    _exact(ar, _CoefficientArithmeticV3, "coefficient arithmetic")
    _exact(ar.kernel_id, str, "kernel_id")
    _exact(ar.resource_policy_version, int, "resource_policy_version")
    _exact(ar.precision_digits, int, "precision_digits")
    _exact(ar.limit, int, "operation limit")
    _exact(ar.rejected, bool, "rejected latch")
    for count in (ar.operations, ar.leaf_operations, ar.reserved_units):
        _exact(count, int, "coefficient accounting count")
        if count < 0:
            raise ValueError("negative coefficient accounting count")
    if (ar.kernel_id != "incremental-j2-jet-v1" or
            ar.resource_policy_version != 3 or
            not 40 <= ar.precision_digits <= 80 or
            not 1 <= ar.limit <= 2**31 or
            ar.operations > ar.limit or
            ar.operations != ar.leaf_operations + ar.reserved_units):
        raise ValueError("incompatible coefficient arithmetic identity/state")
    if ar.rejected:
        raise _Unresolved("primitive work ceiling already rejected")
    ar.reserve(512, "incremental coefficient admission/control")
    try:
        required_traps = {InvalidOperation, DivisionByZero, Overflow,
                          Underflow, Subnormal}
        for owned, rounding in ((ar.down, ROUND_FLOOR),
                                (ar.up, ROUND_CEILING),
                                (ar.nearest, ROUND_HALF_EVEN)):
            _exact(owned, _Context, "coefficient context")
            if owned._ar is not ar:
                raise ValueError("foreign coefficient context owner")
            native = owned._context
            _exact(native, Context, "native coefficient context")
            if (native.prec != ar.precision_digits or native.rounding != rounding or
                    native.Emin != -200 or native.Emax != 200 or
                    native.clamp != 0 or native.capitals != 1 or
                    {signal for signal, enabled in native.traps.items() if enabled}
                    != required_traps):
                raise ValueError("incompatible coefficient context settings")
        _exact(order, int, "coefficient order")
        if order not in (6, 7):
            raise ValueError("coefficient order must be six or seven")
        _exact(box, tuple, "coefficient box")
        if len(box) != 6:
            raise ValueError("coefficient box must have six intervals")
        for interval in box:
            _exact(interval, _I, "coefficient interval")
            for endpoint in (interval.lo, interval.hi):
                _exact(endpoint, _D, "coefficient endpoint")
                if endpoint._ar is not ar:
                    raise ValueError("foreign coefficient endpoint owner")
                ar.charge()  # actual finite guard, before consulting Decimal
                if not endpoint.is_finite():
                    raise ValueError("coefficient endpoint must be finite")
            if interval.lo > interval.hi:  # guarded comparison charges itself
                raise ValueError("coefficient endpoints must be ordered")
        _exact(model, _coast.J2GravityModel, "coefficient gravity model")
        parameters = (model.gravitational_parameter_m3_s2,
                      model.j2, model.reference_radius_m)
        for parameter in parameters:
            _reserve_parameter_metadata(parameter, ar)
            # This private kernel consumes an already-normalized authority,
            # never a raw Real input that could invoke caller numeric hooks.
            _exact(parameter.value, float, "normalized gravity value")
            ar.charge()
            if not isfinite(parameter.value):
                raise ValueError("normalized gravity value must be finite")
            bounds = parameter.provenance.sensitivity_range
            if bounds is not None:
                _exact(bounds, _CoefficientSensitivityRange, "sensitivity_range")
                for value in (bounds.lower, bounds.upper):
                    _exact(value, float, "normalized sensitivity bound")
                    ar.charge()
                    if not isfinite(value):
                        raise ValueError("normalized sensitivity bound must be finite")
        normalized = _coast.J2GravityModel(*parameters)
        rebuilt_parameters = (normalized.gravitational_parameter_m3_s2,
                              normalized.j2, normalized.reference_radius_m)
        for original, rebuilt in zip(parameters, rebuilt_parameters):
            # Compare represented floats (including canonical zero) only after
            # strict primitive ownership and complete model reconstruction.
            ar.charge(2)
            original_hex, rebuilt_hex = original.value.hex(), rebuilt.value.hex()
            ar.charge()
            if original_hex != rebuilt_hex:
                raise ValueError("gravity authority must already be normalized")
            old_bounds = original.provenance.sensitivity_range
            new_bounds = rebuilt.provenance.sensitivity_range
            if old_bounds is not None:
                ar.charge(4)
                old_hex = (old_bounds.lower.hex(), old_bounds.upper.hex())
                new_hex = (new_bounds.lower.hex(), new_bounds.upper.hex())
                ar.charge()
                if old_hex != new_hex:
                    raise ValueError("sensitivity authority must already be normalized")
            # Safe dataclass comparison: numeric fields are exact finite floats,
            # and reconstructed metadata has passed existing strict owners.
            # Its complete text/structure scans were prepaid above.
            ar.charge()
            if original != rebuilt:
                raise ValueError("gravity authority roundtrip changed metadata")
        # Six output jets of N+1 entries plus at most22 intermediate jets of N
        # entries:28N+6 retained interval slots.64 extra slots bound simultaneous
        # products/point constants and other interval scratch. Eight units per
        # slot pay allocation/control; executed numeric leaves are additional.
        ar.reserve(8 * (28 * order + 70),
                   "incremental coefficient bounded workspace/control")
        # At degree m the conservative control count is at most248m+832,
        # bounded by1024(m+1). Reserve the complete finite schedule up front.
        # It pays no fictitious repeated protected arithmetic leaves.
        ar.reserve(1024 * order * (order + 1) // 2,
                   "incremental coefficient degree-control schedule")
        series = [[interval] for interval in box]
        squares = [[], [], []]
        q, b, b2, b3 = [], [], [], []
        has_j2 = normalized.j2.value != 0
        b5, b7, z2b7 = ([], [], []) if has_j2 else (None, None, None)
        central = [[], [], []]
        terms = [[], [], []] if has_j2 else None
        corrections = [[], [], []] if has_j2 else None
        accelerations = [[], [], []]
        mu = factor = None
        for degree in range(order):
            def product_coefficient(left, right):
                # Preserve j=0..degree products and zero-start left-to-right sum.
                return ar.total(ar.mul(left[j], right[degree-j])
                                for j in range(degree+1))

            for axis in range(3):
                value = product_coefficient(series[axis], series[axis])
                if degree == 0:
                    # The discarded product is intentional compatibility work.
                    # Its first evaluation precedes the dependency-tight square.
                    value = ar.square(series[axis][0])
                squares[axis].append(value)
            q.append(ar.total(squares[axis][degree] for axis in range(3)))
            if degree == 0:
                b.append(ar.div(ar.point(1), ar.sqrt(q[0])))
            else:
                recurrence = (ar.mul(ar.point(i/2-degree),
                                     ar.mul(q[i], b[degree-i]))
                              for i in range(1, degree+1))
                b.append(ar.div(ar.total(recurrence),
                                ar.mul(ar.point(degree), q[0])))
            b2.append(product_coefficient(b, b))
            b3.append(product_coefficient(b2, b))
            if degree == 0:
                mu = ar.point(normalized.gravitational_parameter_m3_s2.value)
            for axis in range(3):
                central[axis].append(ar.neg(ar.mul(
                    mu, product_coefficient(series[axis], b3))))
            if has_j2:
                b5.append(product_coefficient(b3, b2))
                b7.append(product_coefficient(b5, b2))
                z2b7.append(product_coefficient(squares[2], b7))
                if degree == 0:
                    factor = ar.mul(ar.point(1.5), ar.mul(mu, ar.mul(
                        ar.point(normalized.j2.value),
                        ar.square(ar.point(normalized.reference_radius_m.value)))))
                for axis in range(3):
                    terms[axis].append(ar.sub(
                        ar.mul(ar.point(5), z2b7[degree]),
                        ar.mul(ar.point(3 if axis == 2 else 1), b5[degree])))
                    corrections[axis].append(product_coefficient(series[axis], terms[axis]))
                    accelerations[axis].append(ar.add(
                        central[axis][degree], ar.mul(factor, corrections[axis][degree])))
            else:
                for axis in range(3):
                    accelerations[axis].append(central[axis][degree])
            rhs = [series[axis+3][degree] for axis in range(3)] + [
                accelerations[axis][degree] for axis in range(3)]
            for axis in range(6):
                series[axis].append(ar.div(rhs[axis], ar.point(degree+1)))
        return series
    except (DecimalException, OverflowError) as error:
        raise _Unresolved("incremental coefficient arithmetic failed: " + str(error)) from error

# M2-B29: explicit opt-in endpoint v3; accepted prefix above remains frozen.

@dataclass(frozen=True, slots=True)
class J2ZonotopePolicyV3(J2ZonotopePolicyV2):
    """Same PB6 model/domain; one cumulative incremental resource-v3 ledger."""

    resource_policy_version: int = field(init=False, default=3)
    kernel_id: str = field(init=False, default="incremental-j2-jet-v1")

    def __post_init__(self) -> None:
        J2ZonotopePolicyV2.__post_init__(self)


def _check_v3_policy_identity(policy):
    _check_method_identity(policy)
    for name, value in (("resource_policy_version", 3), ("pb_order", 6),
                        ("max_generators", 12), ("retained_generators", 6),
                        ("rank_bit_cap", 4096)):
        _exact(getattr(policy, name), int, name)
        if getattr(policy, name) != value:
            raise ValueError("unsupported v3 " + name)
    _exact(policy.kernel_id, str, "kernel_id")
    if policy.kernel_id != "incremental-j2-jet-v1":
        raise ValueError("unsupported v3 coefficient kernel identity")


def _transport_step_v3(z, h, model, policy, ar, step_index=0, next_time=None):
    """One all-set step; return its complete SI Picard tube, not samples."""
    ar.reserve(_NEW_STEP_CONTROL_RESERVATION, "new step bounded control/allocation")
    ar.attempted_steps += 1
    p, scales = policy.base_policy, policy.scale_exponents
    box = _project_box(z, scales, ar)
    ar.reserve(_TUBE_CONTROL_RESERVATION, "unchanged tube bounded legacy control/conversions")
    tube, _ = _old._tube(box, h, model, p, ar)
    center_box = tuple(_I(_shift(c, scale, ar), _shift(c, scale, ar))
                       for c, scale in zip(z.center, scales))
    polynomial = _coefficients_incremental_v1(center_box, 6, model, ar)
    ar.reserve(8, "v3 six-interval coefficient tuple adapter")
    remainder = _coefficients_incremental_v1(tuple(tube), 7, model, ar)
    yc = []
    for axis, (coefficients, derivatives) in enumerate(zip(polynomial, remainder)):
        value = derivatives[7]
        for order in range(6, -1, -1):
            value = ar.add(coefficients[order], ar.mul(h, value))
        yc.append(_I(_shift(value.lo, -scales[axis], ar),
                     _shift(value.hi, -scales[axis], ar)))
    jacobian = _jacobian_box(tube, model, scales, ar)
    matrix = _flow_derivative_box(jacobian, h, ar)
    candidate = _transport_generators(z, yc, matrix, ar, step_index)
    if next_time is None:
        # Private test convenience: only a point duration has exact time authority.
        if ar.point(h.lo).lo != ar.point(h.hi).hi:
            raise _Unresolved("next_time required for interval duration")
        next_time = _radd(z.time, _fraction(h.lo, ar), ar)
    _check_fraction_bits(next_time, ar)
    candidate = _Zonotope(candidate.center, candidate.generators, candidate.births, next_time)
    final_box = _project_box(candidate, scales, ar)
    ar.reserve(128, "unchanged endpoint-domain control/conversions")
    _old._domain(final_box, p, ar)
    ar.completed_steps += 1
    return candidate, tuple(tube)

@dataclass(frozen=True, slots=True)
class J2ZonotopeResultV3(J2ZonotopeResult):
    """Atomic original-anchor endpoint with distinct cumulative resources."""

    policy: J2ZonotopePolicyV3
    resource_policy_version: int = field(init=False, default=3)
    kernel_id: str = field(init=False, default="incremental-j2-jet-v1")
    budget_rejected: bool = field(init=False, default=False)

    __hash__ = None

    def __post_init__(self):
        _exact(self.trajectory, _coast.J2CartesianTrajectory, "trajectory")
        _exact(self.solver_config, _coast.J2RK4SolverConfig, "solver_config")
        _exact(self.policy, J2ZonotopePolicyV3, "policy")
        _check_v3_policy_identity(self.policy)
        _exact(self.policy.base_policy, _old.J2EnclosurePolicy, "base_policy")
        _exact(self.instant, GeometryInstant, "instant")
        ar = _CoefficientArithmeticV3(self.policy.base_policy.precision_digits,
                                      self.policy.max_scalar_operations)
        self._execute(ar)

    def _normalized_policy(self):
        return J2ZonotopePolicyV3(self.policy.base_policy, self.policy.scale_exponents,
                                  self.policy.max_scalar_operations)

    def _execute(self, ar):
        try:
            self._evaluate(ar)
        except Exception as error:
            # Structural bootstrap above still raises. All later computation
            # failures retain diagnostics and never publish success fields.
            object.__setattr__(self, "reason", type(error).__name__ + ": " + str(error))
        finally:
            for key, value in (("attempted_steps", ar.attempted_steps),
                               ("completed_steps", ar.completed_steps),
                               ("picard_attempts", ar.picard_attempts),
                               ("reductions", ar.reductions),
                               ("scalar_operations", ar.operations),
                               ("charged_leaf_operations", ar.leaf_operations),
                               ("reserved_control_operations", ar.reserved_units),
                               ("budget_rejected", ar.rejected)):
                object.__setattr__(self, key, value)

    def _evaluate(self, ar):
        ar.reserve(_ADMISSION_RESERVATION, "bounded static authority/grid admission")
        policy = self._normalized_policy()
        object.__setattr__(self, "policy", policy)
        t = self.trajectory
        _reserve_authority_metadata(t, ar)
        instant = _instant(self.instant)
        config = _coast.J2RK4SolverConfig(self.solver_config.step_seconds,
                                        self.solver_config.max_steps)
        object.__setattr__(self, "instant", instant)
        object.__setattr__(self, "solver_config", config)
        p = policy.base_policy
        state, model = _coast._authorities(t.initial_state, t.gravity_model)
        # Bind normalized immutable authorities without calling the trajectory
        # constructor's F1 admission. F2 performs that admission exactly once.
        ar.charge(3)
        t = object.__new__(_coast.J2CartesianTrajectory)
        object.__setattr__(t, "initial_state", state)
        object.__setattr__(t, "gravity_model", model)
        object.__setattr__(self, "trajectory", t)
        if state.position.instant.epoch != self.instant.epoch:
            raise ValueError("J2 enclosure requires the same TT reference epoch")
        span = _radd(_fraction(self.instant.elapsed_seconds, ar),
                     _fraction(-state.position.instant.elapsed_seconds, ar), ar)
        ar.charge(8)  # exact absolute/divmod/grid count and bound checks
        nf, nr = divmod(abs(span), _fraction(config.step_seconds, ar))
        full, remainder = divmod(abs(span), _fraction(p.step_seconds, ar))
        if abs(span) > 86400 or nf + bool(nr) > min(config.max_steps, 4096) or full + bool(remainder) > p.max_steps:
            raise _Unresolved("horizon or step work ceiling exceeded before integration")
        try:
            _coast._grid(state.position.instant, self.instant, config)
        except ValueError as error:
            raise _Unresolved(str(error)) from error
        values = (*state.position.components_m, *state.velocity.components_m_per_s,
                  model.gravitational_parameter_m3_s2.value, model.j2.value,
                  model.reference_radius_m.value, config.step_seconds)
        if any(value != 0 and not 1e-100 <= abs(value) <= 1e100 for value in values):
            raise _Unresolved("dynamical input outside F3 arithmetic envelope")
        planned = int(nf + bool(nr))
        object.__setattr__(self, "planned_nominal_steps", planned)
        object.__setattr__(self, "planned_nominal_force_calls", 1 + 4 * planned)
        # Prepay unchanged nominal composite/metadata work on this query ledger.
        ar.reserve(4096 * (1 + 4 * planned) + 8192 * planned + 1024,
                   "v3 unchanged F2 bounded composite work")
        for _ in range(1 + 4 * planned + 3):
            _reserve_authority_metadata(t, ar)
        object.__setattr__(self, "nominal_evaluations", 1)
        object.__setattr__(self, "nominal_counter_provenance", "UNKNOWN_PARTIAL_IF_FAILURE")
        try:
            nominal = _nominal_evaluator(t, self.instant, config)
        except (ValueError, OverflowError) as error:
            raise _Unresolved("F2 nominal arithmetic: " + str(error)) from error
        object.__setattr__(self, "nominal_completed_steps", planned)
        object.__setattr__(self, "nominal_force_calls", 1 + 4 * planned)
        object.__setattr__(self, "nominal_counter_provenance", "DERIVED_FROM_SUCCESSFUL_F2_FIXED_GRID")
        z = _initial_set(values[:6], policy.scale_exponents, ar,
                         _fraction(state.position.instant.elapsed_seconds, ar))
        ar.reserve(128, "unchanged initial-domain control/conversions")
        _old._domain(_project_box(z, policy.scale_exponents, ar), p, ar)
        sign = -1 if span < 0 else 1
        for step in range(full + bool(remainder)):
            ar.charge(4)  # bounded exact signed time-grid construction
            dt = _fraction(p.step_seconds, ar) if step < full else remainder
            signed = _rmul(_fraction(sign, ar), dt, ar)
            h = ar.div(ar.point(signed.numerator), ar.point(signed.denominator))
            time = _radd(z.time, signed, ar)
            z, _ = _transport_step_v3(z, h, model, policy, ar, step, time)
        ar.reserve(_FINAL_CONTROL_RESERVATION, "final distance/publication control/allocation")
        box = _project_box(z, policy.scale_exponents, ar)
        components = (*nominal.position.components_m, *nominal.velocity.components_m_per_s)
        radii = tuple(_radius(ar.sub(a, ar.point(value)), ar)
                      for a, value in zip(box, components))
        position = _upper_float(max(radii[:3]), ar)
        velocity = _upper_float(max(radii[3:]), ar)
        endpoints = tuple((_plain(a.lo, ar), _plain(a.hi, ar)) for a in box)
        diagnostic = _plain_set(z, ar)
        # All numeric and allocation checks have passed: publish together.
        for key, value in (("nominal_state", nominal), ("endpoint_intervals", endpoints),
                           ("position_error_bound_m", position),
                           ("velocity_error_bound_m_per_s", velocity),
                           ("diagnostic_state", diagnostic), ("status", "enclosed")):
            object.__setattr__(self, key, value)


def evaluate_j2_zonotope_enclosure_v3(trajectory, instant, solver_config, policy) -> J2ZonotopeResultV3:
    return J2ZonotopeResultV3(trajectory, instant, solver_config, policy)


__all__ += ["J2ZonotopePolicyV3", "J2ZonotopeResultV3",
            "evaluate_j2_zonotope_enclosure_v3"]
