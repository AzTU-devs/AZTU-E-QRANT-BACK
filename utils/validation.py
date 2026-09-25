"""Input validation for money and quantity fields on the budget (smeta) screens.

A negative price, quantity or total lowers the project's budget sum, which is
the only thing the submission check compares against the competition's cap —
so an unchecked value could be used to slip an over-budget proposal through.
"""

import math

MAX_AMOUNT = 10 ** 9


def non_negative_number(value):
    """The value as a number when it is a finite, non-negative amount, else None."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0 or number > MAX_AMOUNT:
        return None
    return int(number) if number.is_integer() else number


def invalid_amount(field):
    return {'error': f'{field} must be a non-negative number.', 'status': 400}, 400
