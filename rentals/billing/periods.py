"""Shared billing-period and proration rules for Rentals.

Monthly lease billing has two supported anchors:

* normal/anniversary billing: the initial recurring charge is a full period and
  the next billing date is one cycle after ``start_date``;
* calendar billing: when ``prorate_first_invoice`` is enabled, the onboarding
  recurring charge covers only the remainder of the start month and normal
  recurring billing begins on the first day of the following month.

The product's historical day-count convention is intentionally preserved:
25 Sep -> 30 Sep is five billable days, i.e. date-boundary subtraction rather
than inclusive calendar-day counting.  Full-period edge cases are handled
explicitly so a lease starting on the first or ending on the last day of its
normal period still bills a full period.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from frappe.utils import add_days, add_months, cint, flt, getdate


SUPPORTED_BILLING_CYCLES = {"Daily", "Monthly", "Quarterly", "Annually"}


def get_next_billing_date(current_date, cycle: str) -> date:
    """Return the next anniversary occurrence for a billing cycle."""
    current_date = getdate(current_date)
    next_date = {
        "Daily": add_days(current_date, 1),
        "Monthly": add_months(current_date, 1),
        "Quarterly": add_months(current_date, 3),
        "Annually": add_months(current_date, 12),
    }.get(cycle)
    if not next_date:
        raise ValueError(f"Unsupported billing cycle: {cycle or 'Not set'}")
    return getdate(next_date)


def get_initial_billing_date(start_date, cycle: str, prorate_first_invoice=False) -> date:
    """Return the first *recurring* billing date after onboarding.

    For a monthly lease with first-invoice proration, onboarding covers the
    partial start month and recurring billing starts on the first of the next
    month.  Otherwise the existing anniversary schedule is retained.
    """
    start_date = getdate(start_date)
    if cycle == "Monthly" and _as_bool(prorate_first_invoice):
        next_month = getdate(add_months(start_date, 1))
        return date(next_month.year, next_month.month, 1)
    return get_next_billing_date(start_date, cycle)


def get_initial_proration_factor(
    *,
    start_date,
    cycle: str,
    prorate_first_invoice=False,
    end_date=None,
    prorate_last_invoice=False,
) -> float:
    """Return the factor for the onboarding recurring charge.

    Security deposits and usage-based utilities must not call this helper.
    Only monthly fixed recurring charges are prorated in the current product
    model.  When the first and last invoice are the same period, the effective
    lease occupancy interval is used once rather than multiplying two factors.
    """
    if cycle != "Monthly":
        return 1.0

    start = getdate(start_date)
    end = getdate(end_date) if end_date else None
    prorate_first = _as_bool(prorate_first_invoice)
    prorate_last = _as_bool(prorate_last_invoice)

    if prorate_first:
        month_end = _month_end(start)
        effective_end = month_end

        # If this onboarding period is also the last lease period, truncate it
        # once at the real end date.  This naturally handles very short leases.
        if prorate_last and end and end < get_initial_billing_date(start, cycle, True):
            effective_end = min(end, month_end)

        if effective_end <= start:
            return 0.0

        # A lease beginning on day 1 has no partial first month unless its end
        # date truncates that same month.
        if start.day == 1 and effective_end == month_end:
            return 1.0

        billable_days = (effective_end - start).days
        return _clamp_factor(billable_days / _days_in_month(start))

    # First proration is off, but a short lease can make the onboarding full
    # anniversary period also be the final period.  Apply last proration here
    # so we do not wait for a recurring occurrence that will never be due.
    if prorate_last and end:
        period_end = get_initial_billing_date(start, cycle, False)
        if end < period_end:
            return _partial_period_factor(start, period_end, end)

    return 1.0


def get_final_proration_factor(
    *,
    period_start,
    cycle: str,
    end_date=None,
    prorate_last_invoice=False,
) -> float:
    """Return the factor for a recurring occurrence that may be the final one."""
    if cycle != "Monthly" or not end_date or not _as_bool(prorate_last_invoice):
        return 1.0

    start = getdate(period_start)
    end = getdate(end_date)
    period_end = get_next_billing_date(start, cycle)

    if end >= period_end:
        return 1.0
    return _partial_period_factor(start, period_end, end)


def get_initial_charge_amount(
    full_amount,
    *,
    start_date,
    cycle: str,
    prorate_first_invoice=False,
    end_date=None,
    prorate_last_invoice=False,
) -> float:
    """Return a fixed recurring onboarding amount after applicable proration."""
    factor = get_initial_proration_factor(
        start_date=start_date,
        cycle=cycle,
        prorate_first_invoice=prorate_first_invoice,
        end_date=end_date,
        prorate_last_invoice=prorate_last_invoice,
    )
    return _amount(full_amount, factor)


def get_recurring_charge_amount(
    full_amount,
    *,
    period_start,
    cycle: str,
    end_date=None,
    prorate_last_invoice=False,
) -> float:
    """Return a recurring fixed charge after applicable final-period proration."""
    factor = get_final_proration_factor(
        period_start=period_start,
        cycle=cycle,
        end_date=end_date,
        prorate_last_invoice=prorate_last_invoice,
    )
    return _amount(full_amount, factor)


def _partial_period_factor(period_start: date, period_end: date, effective_end: date) -> float:
    """Apply the agreed boundary-day convention to a truncated period."""
    if effective_end <= period_start:
        return 0.0

    # The normal period includes the calendar day immediately before its next
    # billing boundary.  Ending on that final day is therefore a full period.
    if effective_end >= period_end - timedelta(days=1):
        return 1.0

    denominator = (period_end - period_start).days
    if denominator <= 0:
        return 0.0
    numerator = (effective_end - period_start).days
    return _clamp_factor(numerator / denominator)


def _month_end(value: date) -> date:
    return date(value.year, value.month, monthrange(value.year, value.month)[1])


def _days_in_month(value: date) -> int:
    return monthrange(value.year, value.month)[1]


def _amount(full_amount, factor: float) -> float:
    # Keep enough precision for ERPNext's currency/line rounding to make the
    # final accounting decision while avoiding binary floating-point noise.
    return flt(flt(full_amount) * factor, 6)


def _clamp_factor(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return bool(cint(value or 0))
