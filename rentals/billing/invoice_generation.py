"""Period-aware recurring invoice generation for Lease Agreements.

The scheduler and the Lease Agreement manual action both call this module.  A
billing occurrence is identified by ``Lease Agreement + billing period date``
so retries and scheduler/manual races are idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

from rentals.billing.periods import (
    get_final_proration_factor,
    get_next_billing_date as _get_next_billing_date,
    get_recurring_charge_amount,
)

MAX_PERIODS_PER_RUN = 366


@dataclass
class DuePeriod:
    billing_date: date
    rent_due: bool
    service_names: set[str]


@frappe.whitelist()
def generate_sales_invoices(
    lease_name=None,
    through_date=None,
    send_notifications=None,
    generation_source=None,
    override_billing_date=False,
):
    """Generate every ungenerated billing occurrence through ``through_date``.

    Scheduler calls omit ``lease_name`` and therefore process all active leases
    through today.  Manual calls provide one lease and may select a future
    ``through_date`` for demos/advance billing.

    ``override_billing_date`` is kept only for backwards compatibility with old
    clients.  It no longer bypasses billing cycles: period dates remain the
    source of truth.
    """
    target_date = _resolve_through_date(through_date)
    manual = bool(lease_name)
    source = generation_source or ("Manual" if manual else "Scheduler")
    if source not in {"Manual", "Scheduler"}:
        frappe.throw(_("Generation Source must be Manual or Scheduler."))
    notify = _as_bool(send_notifications, default=not manual)

    leases = get_target_leases(lease_name)
    created_invoices = []
    skipped_periods = []
    processed = []

    for lease in leases:
        lease_doc = frappe.get_doc("Lease Agreement", lease["name"])
        _validate_lease_for_generation(lease_doc)

        result = generate_lease_invoices_through(
            lease_doc=lease_doc,
            through_date=target_date,
            generation_source=source,
            send_notifications=notify,
        )
        created_invoices.extend(result["invoices"])
        skipped_periods.extend(result["skipped_periods"])
        processed.extend(result["periods"])

    if created_invoices:
        message = _("Sales Invoice(s) generated successfully.")
    elif skipped_periods:
        message = _("No new Sales Invoices were created; matching billing periods already exist.")
    else:
        message = _("No Sales Invoices were due through the selected date.")

    return {
        "message": message,
        "invoices": created_invoices,
        "periods": processed,
        "skipped_periods": skipped_periods,
        "through_date": str(target_date),
    }


@frappe.whitelist()
def preview_invoice_generation(lease_name, through_date):
    """Preview periods and projected balances without creating documents."""
    if not lease_name:
        frappe.throw(_("Lease Agreement is required."))

    lease_doc = frappe.get_doc("Lease Agreement", lease_name)
    _validate_lease_for_generation(lease_doc)
    target_date = _effective_through_date(lease_doc, _resolve_through_date(through_date))

    state = _build_schedule_state(lease_doc)
    periods = []
    projected_balance = _get_lease_outstanding_before(lease_doc.name, _next_state_date(state) or target_date)
    consumed_utility_logs: set[str] = set()

    for _ in range(MAX_PERIODS_PER_RUN):
        period = _peek_due_period(state, target_date)
        if not period:
            break

        items = _build_recurring_items_from_state(lease_doc, state, period)
        utility_items, utility_logs = _get_utility_items(
            lease_doc,
            period.billing_date,
            exclude_logs=consumed_utility_logs,
        )
        items.extend(utility_items)
        consumed_utility_logs.update(log.name for log in utility_logs)

        if not items and _is_zero_day_final_period(lease_doc, period):
            _advance_state(state, period)
            continue

        current_charges = _item_total(items)
        existing_invoice = _find_existing_period_invoice(lease_doc.name, period.billing_date)
        existing_outstanding = 0
        if existing_invoice:
            summary = frappe.db.get_value(
                "Sales Invoice",
                existing_invoice,
                ["grand_total", "outstanding_amount"],
                as_dict=True,
            )
            if summary:
                current_charges = flt(summary.grand_total)
                existing_outstanding = max(flt(summary.outstanding_amount), 0)

        periods.append(
            {
                "billing_date": str(period.billing_date),
                "previous_balance": projected_balance,
                "current_charges": current_charges,
                "projected_account_due": projected_balance + (existing_outstanding if existing_invoice else current_charges),
                "existing_invoice": existing_invoice,
            }
        )

        projected_balance += existing_outstanding if existing_invoice else current_charges
        _advance_state(state, period)
    else:
        frappe.throw(_("The selected range exceeds the maximum of {0} billing periods per run.").format(MAX_PERIODS_PER_RUN))

    return {
        "lease": lease_doc.name,
        "through_date": str(target_date),
        "period_count": len(periods),
        "periods": periods,
        "has_future_periods": any(getdate(row["billing_date"]) > getdate(nowdate()) for row in periods),
    }


def generate_lease_invoices_through(lease_doc, through_date, generation_source, send_notifications):
    """Generate all due occurrences for one lease through a target date."""
    target_date = _effective_through_date(lease_doc, getdate(through_date))
    created = []
    skipped = []
    periods = []

    # Apply any existing unallocated payments before capturing brought-forward
    # balances on new invoices.
    attempt_reconciliation(lease_doc.customer, lease_doc.company)

    for _ in range(MAX_PERIODS_PER_RUN):
        period = _get_next_due_period(lease_doc, target_date)
        if not period:
            break

        existing_invoice = _find_existing_period_invoice(lease_doc.name, period.billing_date)
        if existing_invoice:
            skipped.append({"billing_date": str(period.billing_date), "invoice": existing_invoice})
            _advance_lease_schedule(lease_doc, period)
            _save_schedule(lease_doc)
            continue

        invoice_items = _build_recurring_items(lease_doc, period)
        utility_items, utility_logs = _get_utility_items(lease_doc, period.billing_date)
        invoice_items.extend(utility_items)

        # A final occurrence exactly on end_date has zero billable days under
        # the agreed boundary-day convention. Advance it without creating a
        # zero-value invoice. Other empty periods still indicate bad data.
        if not invoice_items and _is_zero_day_final_period(lease_doc, period):
            skipped.append({
                "billing_date": str(period.billing_date),
                "reason": _("No billable recurring days remain before lease end."),
            })
            _advance_lease_schedule(lease_doc, period)
            _save_schedule(lease_doc)
            continue

        if not invoice_items:
            frappe.throw(
                _("Billing period {0} for Lease Agreement {1} has no invoiceable items.").format(
                    period.billing_date, lease_doc.name
                )
            )

        invoice = create_sales_invoice(
            lease_doc=lease_doc,
            invoice_items=invoice_items,
            billing_date=period.billing_date,
            generation_source=generation_source,
        )
        created.append(invoice.name)
        periods.append(str(period.billing_date))

        _mark_utility_logs_billed(utility_logs, invoice.name)

        if send_notifications:
            send_invoice_created_sms(lease_doc, invoice)

        # Reconcile after each period so any existing customer credit can reduce
        # outstanding amounts before the next period captures previous balance.
        attempt_reconciliation(lease_doc.customer, lease_doc.company)

        _advance_lease_schedule(lease_doc, period)
        _save_schedule(lease_doc)
    else:
        frappe.throw(_("The selected range exceeds the maximum of {0} billing periods per run.").format(MAX_PERIODS_PER_RUN))

    return {"invoices": created, "skipped_periods": skipped, "periods": periods}


def get_target_leases(lease_name=None):
    """Return submitted active leases, or one explicitly requested lease."""
    if lease_name:
        return [{"name": lease_name}]
    return frappe.get_all(
        "Lease Agreement",
        filters={"status": "Active", "docstatus": 1},
        fields=["name"],
    )


def get_next_billing_date(current_date, cycle):
    """Return the next occurrence for a billing cycle."""
    try:
        return _get_next_billing_date(current_date, cycle)
    except ValueError:
        frappe.throw(_("Unsupported billing cycle: {0}").format(cycle or _("Not set")))


def create_sales_invoice(lease_doc, invoice_items, billing_date, generation_source):
    """Create and submit one idempotent recurring Sales Invoice."""
    billing_date = getdate(billing_date)
    billing_key = _billing_key(lease_doc.name, billing_date)

    existing = _find_existing_period_invoice(lease_doc.name, billing_date)
    if existing:
        return frappe.get_doc("Sales Invoice", existing)

    previous_balance = _get_lease_outstanding_before(lease_doc.name, billing_date)
    invoice = frappe.get_doc(
        {
            "doctype": "Sales Invoice",
            "customer": lease_doc.customer,
            "company": lease_doc.company,
            "due_date": billing_date,
            "posting_date": billing_date,
            "set_posting_time": 1,
            "debit_to": frappe.get_value("Company", lease_doc.company, "default_receivable_account"),
            "currency": lease_doc.billing_currency,
            "selling_price_list": frappe.db.get_value("Customer", lease_doc.customer, "default_price_list"),
            "custom_lease_agreement": lease_doc.name,
            "custom_billing_period": billing_date,
            "custom_billing_key": billing_key,
            "custom_generation_source": generation_source,
            "custom_previous_balance": previous_balance,
            "items": invoice_items,
            "remarks": _("Recurring invoice for Lease Agreement {0}, billing period {1}, generated {2}.").format(
                lease_doc.name, billing_date, generation_source.lower()
            ),
        }
    )
    invoice.flags.ignore_permissions = True
    invoice.insert(ignore_permissions=True)

    # Use ERPNext's calculated grand total rather than duplicating accounting
    # calculation logic.  Previous balance is informational only and is never an
    # invoice item, preventing the old receivable from being recognised twice.
    invoice.custom_current_period_charges = flt(invoice.grand_total)
    invoice.custom_account_due_at_issue = flt(previous_balance) + flt(invoice.grand_total)
    invoice.save(ignore_permissions=True)
    invoice.submit()
    return invoice


def _get_next_due_period(lease_doc, through_date):
    candidates = []
    if lease_doc.rent_item and lease_doc.billing_date:
        candidates.append(getdate(lease_doc.billing_date))

    for service in lease_doc.chargeable_services:
        if service.service and service.billing_date:
            candidates.append(getdate(service.billing_date))

    if not candidates:
        return None

    billing_date = min(candidates)
    if billing_date > getdate(through_date):
        return None

    return DuePeriod(
        billing_date=billing_date,
        rent_due=bool(lease_doc.rent_item and lease_doc.billing_date and getdate(lease_doc.billing_date) == billing_date),
        service_names={
            service.name
            for service in lease_doc.chargeable_services
            if service.service and service.billing_date and getdate(service.billing_date) == billing_date
        },
    )


def _build_recurring_items(lease_doc, period):
    items = []
    if period.rent_due:
        amount, factor = _recurring_amount_and_factor(
            lease_doc,
            lease_doc.base_rental_amount,
            lease_doc.billing_cycle,
            period.billing_date,
        )
        if amount > 0:
            description = _("Base Rent - billing period {0}").format(period.billing_date)
            if factor < 1:
                description = _("{0} (prorated through {1})").format(description, lease_doc.end_date)
            items.append(
                {
                    "item_code": lease_doc.rent_item,
                    "qty": 1,
                    "rate": amount,
                    "description": description,
                }
            )

    for service in lease_doc.chargeable_services:
        if service.name in period.service_names:
            amount, factor = _recurring_amount_and_factor(
                lease_doc, service.rate, service.billing_cycle, period.billing_date
            )
            if amount <= 0:
                continue
            description = _("{0} - billing period {1}").format(service.billing_cycle, period.billing_date)
            if factor < 1:
                description = _("{0} (prorated through {1})").format(description, lease_doc.end_date)
            items.append(
                {
                    "item_code": service.service,
                    "qty": 1,
                    "rate": amount,
                    "description": description,
                }
            )
    return items


def _recurring_amount_and_factor(lease_doc, full_amount, cycle, period_start):
    factor = get_final_proration_factor(
        period_start=period_start,
        cycle=cycle,
        end_date=lease_doc.end_date,
        prorate_last_invoice=lease_doc.prorate_last_invoice,
    )
    amount = get_recurring_charge_amount(
        full_amount,
        period_start=period_start,
        cycle=cycle,
        end_date=lease_doc.end_date,
        prorate_last_invoice=lease_doc.prorate_last_invoice,
    )
    return amount, factor


def _get_utility_items(lease_doc, billing_date, exclude_logs=None):
    """Return open utility logs available on/before this billing occurrence.

    Utility Bill Log has no explicit service-period field in the current app, so
    its creation date is the safest existing boundary.  This prevents an open
    reading created later from being pulled backwards into an earlier invoice.
    """
    exclude_logs = exclude_logs or set()
    rows = frappe.get_all(
        "Utility Bill Log",
        filters={"status": "Open", "lease_agreement": lease_doc.name},
        fields=["name", "creation"],
        order_by="creation asc",
    )

    items = []
    included_logs = []
    for row in rows:
        if row.name in exclude_logs or getdate(row.creation) > getdate(billing_date):
            continue

        log_doc = frappe.get_doc("Utility Bill Log", row.name)
        rate = frappe.db.get_value(
            "Utility Rate",
            {"utility_provider": log_doc.utility_provider, "utility": log_doc.utility},
            ["name", "rate_type", "flat_rate"],
            as_dict=True,
        )
        if not rate:
            frappe.logger().warning("No Utility Rate found for %s", log_doc.utility)
            continue

        before = len(items)
        if rate.rate_type == "Flat":
            items.append(
                {
                    "item_code": log_doc.utility,
                    "qty": log_doc.units_used,
                    "rate": rate.flat_rate,
                    "description": _("{0} units @ flat rate").format(log_doc.units_used),
                }
            )
        elif rate.rate_type == "Slab":
            _add_slab_items(log_doc, rate.name, items)

        if len(items) > before:
            included_logs.append(log_doc)

    return items, included_logs


def _add_slab_items(log_doc, rate_name, invoice_items):
    rate_doc = frappe.get_doc("Utility Rate", rate_name)
    remaining_units = flt(log_doc.units_used)

    for slab in sorted(rate_doc.slab_rate, key=lambda row: row.from_units):
        if remaining_units <= 0:
            break

        from_units = flt(slab.from_units)
        to_units = flt(slab.to_units) if slab.to_units is not None else None
        slab_capacity = (to_units - from_units + 1) if to_units is not None else remaining_units
        slab_units = min(remaining_units, slab_capacity)
        if slab_units <= 0:
            continue

        invoice_items.append(
            {
                "item_code": log_doc.utility,
                "qty": slab_units,
                "rate": slab.rate,
                "description": _("{0} units from {1} to {2} @ {3}").format(
                    slab_units,
                    from_units,
                    to_units if to_units is not None else "∞",
                    slab.rate,
                ),
            }
        )
        remaining_units -= slab_units


def _mark_utility_logs_billed(log_docs, invoice_name):
    for log_doc in log_docs:
        log_doc.status = "Billed"
        # Field is optional for backwards compatibility; the fixture adds it.
        if log_doc.meta.has_field("sales_invoice"):
            log_doc.sales_invoice = invoice_name
        log_doc.save(ignore_permissions=True)


def _advance_lease_schedule(lease_doc, period):
    if period.rent_due:
        lease_doc.billing_date = get_next_billing_date(period.billing_date, lease_doc.billing_cycle)

    for service in lease_doc.chargeable_services:
        if service.name in period.service_names:
            service.billing_date = get_next_billing_date(period.billing_date, service.billing_cycle)


def _save_schedule(lease_doc):
    """Persist scheduler-maintained dates on a submitted lease."""
    lease_doc.flags.ignore_validate_update_after_submit = True
    lease_doc.save(ignore_permissions=True)


def _find_existing_period_invoice(lease_name, billing_date):
    billing_key = _billing_key(lease_name, billing_date)
    invoice = frappe.db.get_value(
        "Sales Invoice",
        {"custom_billing_key": billing_key, "docstatus": ["!=", 2]},
        "name",
    )
    if invoice:
        return invoice

    # Upgrade-safe fallback: invoices created by the previous generator do not
    # have custom_billing_key.  Recognise its distinctive remarks so a stale
    # lease billing_date cannot cause a duplicate immediately after deployment.
    legacy = frappe.get_all(
        "Sales Invoice",
        filters={
            "custom_lease_agreement": lease_name,
            "posting_date": getdate(billing_date),
            "docstatus": ["!=", 2],
            "remarks": ["like", f"Invoice for Lease Agreement {lease_name} generated%"],
        },
        pluck="name",
        limit_page_length=1,
    )
    return legacy[0] if legacy else None


def _billing_key(lease_name, billing_date):
    return f"{lease_name}::{getdate(billing_date).isoformat()}"


def _get_lease_outstanding_before(lease_name, billing_date):
    result = frappe.db.sql(
        """
        SELECT COALESCE(SUM(outstanding_amount), 0)
        FROM `tabSales Invoice`
        WHERE docstatus = 1
          AND custom_lease_agreement = %s
          AND posting_date < %s
          AND outstanding_amount > 0
        """,
        (lease_name, getdate(billing_date)),
    )
    return flt(result[0][0] if result else 0)


def attempt_reconciliation(customer, company):
    """Auto-reconcile available customer payments against outstanding invoices."""
    try:
        doc = frappe.new_doc("Payment Reconciliation")
        doc.party_type = "Customer"
        doc.party = customer
        doc.company = company
        doc.receivable_payable_account = frappe.get_value("Company", company, "default_receivable_account")
        doc.get_unreconciled_entries()

        if not doc.invoices or not doc.payments:
            return

        doc.allocate_entries(
            {
                "payments": [row.as_dict() for row in doc.payments],
                "invoices": [row.as_dict() for row in doc.invoices],
            }
        )
        doc.save()
        doc.reconcile()
    except Exception:
        # Reconciliation should not make valid billing impossible.  Preserve the
        # existing behaviour but keep a full traceback in Error Log.
        frappe.log_error(frappe.get_traceback(), _("Auto Reconciliation Error"))


def send_invoice_created_sms(lease_doc, invoice):
    try:
        from rentals.sms.transactional import send_invoice_created_sms as queue_invoice_sms

        queue_invoice_sms(lease_doc, invoice)
    except Exception:
        frappe.log_error(frappe.get_traceback(), _("Invoice Created SMS Error"))


def _validate_lease_for_generation(lease_doc):
    if lease_doc.docstatus != 1:
        frappe.throw(_("Lease Agreement {0} must be submitted before invoices can be generated.").format(lease_doc.name))
    if lease_doc.status != "Active":
        frappe.throw(_("Lease Agreement {0} is not Active.").format(lease_doc.name))
    if not lease_doc.customer or not lease_doc.company:
        frappe.throw(_("Lease Agreement {0} requires both Customer and Company.").format(lease_doc.name))


def _is_zero_day_final_period(lease_doc, period):
    return bool(
        lease_doc.end_date
        and cint(lease_doc.prorate_last_invoice)
        and getdate(period.billing_date) >= getdate(lease_doc.end_date)
    )


def _effective_through_date(lease_doc, target_date):
    target_date = getdate(target_date)
    if lease_doc.end_date:
        target_date = min(target_date, getdate(lease_doc.end_date))
    return target_date


def _resolve_through_date(value):
    return getdate(value or nowdate())


def _as_bool(value, default=False):
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return bool(cint(value))


def _item_total(items):
    return sum(flt(row.get("qty")) * flt(row.get("rate")) for row in items)


# Preview-only schedule helpers -------------------------------------------------

def _build_schedule_state(lease_doc):
    return {
        "rent": {
            "date": getdate(lease_doc.billing_date) if lease_doc.rent_item and lease_doc.billing_date else None,
            "cycle": lease_doc.billing_cycle,
            "item": lease_doc.rent_item,
            "rate": lease_doc.base_rental_amount,
        },
        "services": {
            row.name: {
                "date": getdate(row.billing_date) if row.service and row.billing_date else None,
                "cycle": row.billing_cycle,
                "item": row.service,
                "rate": row.rate,
            }
            for row in lease_doc.chargeable_services
            if row.service
        },
    }


def _next_state_date(state):
    dates = []
    if state["rent"]["date"]:
        dates.append(state["rent"]["date"])
    dates.extend(row["date"] for row in state["services"].values() if row["date"])
    return min(dates) if dates else None


def _peek_due_period(state, through_date):
    billing_date = _next_state_date(state)
    if not billing_date or billing_date > getdate(through_date):
        return None
    return DuePeriod(
        billing_date=billing_date,
        rent_due=state["rent"]["date"] == billing_date,
        service_names={name for name, row in state["services"].items() if row["date"] == billing_date},
    )


def _build_recurring_items_from_state(lease_doc, state, period):
    items = []
    if period.rent_due:
        amount = get_recurring_charge_amount(
            state["rent"]["rate"],
            period_start=period.billing_date,
            cycle=state["rent"]["cycle"],
            end_date=lease_doc.end_date,
            prorate_last_invoice=lease_doc.prorate_last_invoice,
        )
        if amount > 0:
            items.append({"item_code": state["rent"]["item"], "qty": 1, "rate": amount})
    for name in period.service_names:
        row = state["services"][name]
        amount = get_recurring_charge_amount(
            row["rate"],
            period_start=period.billing_date,
            cycle=row["cycle"],
            end_date=lease_doc.end_date,
            prorate_last_invoice=lease_doc.prorate_last_invoice,
        )
        if amount > 0:
            items.append({"item_code": row["item"], "qty": 1, "rate": amount})
    return items


def _advance_state(state, period):
    if period.rent_due:
        state["rent"]["date"] = get_next_billing_date(period.billing_date, state["rent"]["cycle"])
    for name in period.service_names:
        row = state["services"][name]
        row["date"] = get_next_billing_date(period.billing_date, row["cycle"])
