"""
Automated SMS reminders for Rentals.

Handles daily scheduled reminders for:
- upcoming rent due dates based on Lease Agreement.billing_date
- overdue Sales Invoices linked to Lease Agreements
- upcoming Lease Agreement expiry dates
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cint, date_diff, flt, formatdate, getdate, nowdate

from rentals.sms.africas_talking import SMS_LOG_DOCTYPE, SMS_SETTINGS_DOCTYPE, send_sms
from rentals.sms.templates import render_sms_template
from rentals.sms.utils import SMSValidationError


RENT_DUE_REMINDER = "Rent Due"
OVERDUE_INVOICE_REMINDER = "Overdue Invoice"
LEASE_EXPIRY_REMINDER = "Lease Expiry"

RENT_DUE_TEMPLATE = "Rent Due Reminder"
OVERDUE_INVOICE_TEMPLATE = "Overdue Invoice Reminder"
LEASE_EXPIRY_TEMPLATE = "Lease Expiry Reminder"

FAILED_STATUSES = (
	"Failed",
	"Rejected",
	"InvalidPhoneNumber",
	"InsufficientBalance",
	"UserInBlacklist",
	"NotSent",
)


def _get_settings():
	"""Return Rentals SMS Settings, or None when SMS is not installed yet."""
	try:
		if not frappe.db.exists("DocType", SMS_SETTINGS_DOCTYPE):
			return None
		return frappe.get_single(SMS_SETTINGS_DOCTYPE)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Reminder Settings Lookup Error")
		return None


def _is_enabled(settings, fieldname: str) -> bool:
	return bool(settings and settings.enabled and getattr(settings, fieldname, 0))


def _parse_days(value: str | None, default: str) -> set[int]:
	"""Parse comma/semicolon/pipe separated day offsets into a set of ints."""
	value = (value or default or "").replace(";", ",").replace("|", ",")
	days: set[int] = set()

	for raw_part in value.split(","):
		part = raw_part.strip()
		if not part or not part.isdigit():
			continue
		days.add(cint(part))

	return days


def _safe_limit(settings) -> int:
	limit = cint(getattr(settings, "reminder_sms_limit_per_run", 0) or 0)
	return limit if limit > 0 else 500


def _first_present(*values: Any) -> Any | None:
	for value in values:
		if value not in (None, ""):
			return value
	return None


def _format_money(currency: str | None, amount: float | int | str | None) -> str:
	currency = currency or "KES"
	value = flt(amount)

	if value == int(value):
		return f"{currency} {int(value):,}"

	return f"{currency} {value:,.2f}"


def _format_days_text(days: int) -> str:
	if days == 0:
		return "today"
	if days == 1:
		return "in 1 day"
	return f"in {days} days"


def _format_overdue_days_text(days: int) -> str:
	if days == 1:
		return "1 day"
	return f"{days} days"


def _render_configured_reminder_template(
	*,
	settings,
	settings_fieldname: str,
	template_type: str,
	context: dict[str, Any],
	fallback_message: str,
) -> tuple[str, str | None]:
	"""Render a configured/default reminder template, or return fallback."""
	return render_sms_template(
		template_name=getattr(settings, settings_fieldname, None),
		template_type=template_type,
		context=context,
		fallback_message=fallback_message,
	)


def _get_tenant_details(lease_row: dict[str, Any]) -> dict[str, Any]:
	"""Resolve tenant name and phone from lease values plus linked Tenant fallback."""
	tenant = lease_row.get("tenant")
	tenant_row = None

	if tenant:
		tenant_row = frappe.db.get_value(
			"Tenant",
			tenant,
			["full_name", "phone_number", "mobile_no"],
			as_dict=True,
		)

	tenant_row = tenant_row or {}
	return {
		"tenant": tenant,
		"tenant_name": _first_present(
			lease_row.get("tenant_name"),
			tenant_row.get("full_name"),
			tenant,
			"Tenant",
		),
		"phone_number": _first_present(
			lease_row.get("tenant_phone_number"),
			tenant_row.get("phone_number"),
			tenant_row.get("mobile_no"),
		),
	}


def _property_label(lease_row: dict[str, Any]) -> str | None:
	property_name = _first_present(lease_row.get("property_name"), lease_row.get("property"))
	unit = lease_row.get("unit")

	if property_name and unit:
		return f"{property_name}, Unit {unit}"
	if property_name:
		return str(property_name)
	if unit:
		return f"Unit {unit}"
	return None


def _reminder_already_logged(
	*,
	reminder_type: str,
	reference_doctype: str,
	reference_name: str,
	reminder_date: str,
) -> bool:
	"""Prevent duplicate reminder sends for the same record on the same day."""
	try:
		rows = frappe.get_all(
			SMS_LOG_DOCTYPE,
			filters={
				"reminder_type": reminder_type,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"reminder_date": reminder_date,
				"status": ["not in", FAILED_STATUSES],
			},
			fields=["name"],
			limit=1,
		)
		return bool(rows)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Reminder Duplicate Check Error")
		return False


def _send_reminder_sms(
	*,
	phone_number: str | None,
	message: str,
	reminder_type: str,
	reminder_date: str,
	recipient_doctype: str | None = None,
	recipient_name: str | None = None,
	reference_doctype: str,
	reference_name: str,
	sms_template: str | None = None,
) -> dict[str, Any]:
	"""Send one reminder SMS with duplicate protection and reminder tracking."""
	if not phone_number:
		return {"ok": False, "skipped": True, "reason": "Missing phone number."}

	if _reminder_already_logged(
		reminder_type=reminder_type,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		reminder_date=reminder_date,
	):
		return {"ok": True, "skipped": True, "duplicate": True}

	try:
		return send_sms(
			recipients=phone_number,
			message=message,
			recipient_doctype=recipient_doctype,
			recipient_name=recipient_name,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			sms_category="Reminder",
			sms_template=sms_template,
			reminder_type=reminder_type,
			reminder_date=reminder_date,
		)
	except SMSValidationError as exc:
		return {"ok": False, "skipped": True, "reason": str(exc)}
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Rentals {reminder_type} SMS Reminder Error")
		return {"ok": False, "error": frappe.get_traceback()}


def _empty_result() -> dict[str, int]:
	return {
		"matched": 0,
		"sent": 0,
		"skipped": 0,
		"failed": 0,
	}


def _record_result(result: dict[str, int], send_result: dict[str, Any] | None):
	if not send_result:
		result["failed"] += 1
		return

	if send_result.get("skipped"):
		result["skipped"] += 1
		return

	if send_result.get("ok"):
		result["sent"] += 1
		return

	result["failed"] += 1


def send_rent_due_reminders(*, settings=None, reminder_date: str | None = None, limit: int | None = None) -> dict[str, int]:
	"""Send reminders for active leases whose billing date is approaching."""
	settings = settings or _get_settings()
	result = _empty_result()

	if not _is_enabled(settings, "auto_send_rent_due_reminder_sms"):
		return result

	reminder_date = reminder_date or nowdate()
	today = getdate(reminder_date)
	days_before = _parse_days(getattr(settings, "rent_due_reminder_days_before", None), "3,1")
	limit = limit or _safe_limit(settings)

	leases = frappe.get_all(
		"Lease Agreement",
		filters={"docstatus": 1, "status": "Active"},
		fields=[
			"name",
			"tenant",
			"tenant_name",
			"tenant_phone_number",
			"property",
			"property_name",
			"unit",
			"billing_date",
			"base_rental_amount",
			"billing_currency",
		],
		order_by="billing_date asc, tenant_name asc",
	)

	for lease in leases:
		if result["matched"] >= limit:
			break
		if not lease.get("billing_date"):
			continue

		days_until_due = date_diff(getdate(lease.get("billing_date")), today)
		if days_until_due not in days_before:
			continue

		result["matched"] += 1
		tenant = _get_tenant_details(lease)
		amount = _format_money(lease.get("billing_currency"), lease.get("base_rental_amount"))
		due_date = formatdate(lease.get("billing_date"))
		property_label = _property_label(lease)
		property_text = f" for {property_label}" if property_label else ""

		fallback_message = (
			f"Dear {tenant['tenant_name']}, rent for lease {lease.name}{property_text} is due "
			f"{_format_days_text(days_until_due)} on {due_date}. Amount: {amount}. "
			f"Pay using account number {lease.name}."
		)
		context = {
			"tenant": tenant.get("tenant"),
			"tenant_name": tenant.get("tenant_name"),
			"lease_name": lease.name,
			"lease_agreement": lease.name,
			"account_number": lease.name,
			"property": lease.get("property"),
			"property_label": property_label,
			"unit": lease.get("unit"),
			"amount": amount,
			"due_date": due_date,
			"days_until_due": days_until_due,
			"days_text": _format_days_text(days_until_due),
		}
		message, template_used = _render_configured_reminder_template(
			settings=settings,
			settings_fieldname="rent_due_reminder_sms_template",
			template_type=RENT_DUE_TEMPLATE,
			context=context,
			fallback_message=fallback_message,
		)

		_record_result(
			result,
			_send_reminder_sms(
				phone_number=tenant.get("phone_number"),
				message=message,
				reminder_type=RENT_DUE_REMINDER,
				reminder_date=reminder_date,
				recipient_doctype="Tenant" if tenant.get("tenant") else None,
				recipient_name=tenant.get("tenant"),
				reference_doctype="Lease Agreement",
				reference_name=lease.name,
				sms_template=template_used,
			),
		)

	return result


def send_overdue_invoice_reminders(*, settings=None, reminder_date: str | None = None, limit: int | None = None) -> dict[str, int]:
	"""Send reminders for overdue unpaid Sales Invoices linked to leases."""
	settings = settings or _get_settings()
	result = _empty_result()

	if not _is_enabled(settings, "auto_send_overdue_invoice_reminder_sms"):
		return result

	reminder_date = reminder_date or nowdate()
	today = getdate(reminder_date)
	days_after = _parse_days(getattr(settings, "overdue_invoice_reminder_days_after", None), "1,3,7,14,30")
	limit = limit or _safe_limit(settings)

	invoices = frappe.db.sql(
		"""
		select
			si.name,
			si.custom_lease_agreement,
			si.outstanding_amount,
			si.due_date,
			si.currency
		from `tabSales Invoice` si
		where si.docstatus = 1
		  and si.outstanding_amount > 0
		  and si.due_date < %(today)s
		  and ifnull(si.custom_lease_agreement, '') != ''
		order by si.due_date asc, si.name asc
		""",
		{"today": today},
		as_dict=True,
	)

	for invoice in invoices:
		if result["matched"] >= limit:
			break

		days_overdue = date_diff(today, getdate(invoice.get("due_date")))
		if days_overdue not in days_after:
			continue

		lease_name = invoice.get("custom_lease_agreement")
		lease = frappe.db.get_value(
			"Lease Agreement",
			lease_name,
			["name", "tenant", "tenant_name", "tenant_phone_number", "property", "property_name", "unit", "billing_currency"],
			as_dict=True,
		)
		if not lease:
			continue

		result["matched"] += 1
		tenant = _get_tenant_details(lease)
		amount = _format_money(invoice.get("currency") or lease.get("billing_currency"), invoice.get("outstanding_amount"))
		property_label = _property_label(lease)
		property_text = f" for {property_label}" if property_label else ""

		fallback_message = (
			f"Dear {tenant['tenant_name']}, invoice {invoice.name}{property_text} is overdue by "
			f"{_format_overdue_days_text(days_overdue)}. Outstanding amount: {amount}. "
			f"Pay using account number {lease.name}."
		)
		context = {
			"tenant": tenant.get("tenant"),
			"tenant_name": tenant.get("tenant_name"),
			"invoice_name": invoice.name,
			"invoice": invoice.name,
			"lease_name": lease.name,
			"lease_agreement": lease.name,
			"account_number": lease.name,
			"property": lease.get("property"),
			"property_label": property_label,
			"amount": amount,
			"due_date": formatdate(invoice.get("due_date")),
			"days_overdue": days_overdue,
			"days_text": _format_overdue_days_text(days_overdue),
		}
		message, template_used = _render_configured_reminder_template(
			settings=settings,
			settings_fieldname="overdue_invoice_reminder_sms_template",
			template_type=OVERDUE_INVOICE_TEMPLATE,
			context=context,
			fallback_message=fallback_message,
		)

		_record_result(
			result,
			_send_reminder_sms(
				phone_number=tenant.get("phone_number"),
				message=message,
				reminder_type=OVERDUE_INVOICE_REMINDER,
				reminder_date=reminder_date,
				recipient_doctype="Tenant" if tenant.get("tenant") else None,
				recipient_name=tenant.get("tenant"),
				reference_doctype="Sales Invoice",
				reference_name=invoice.name,
				sms_template=template_used,
			),
		)

	return result


def send_lease_expiry_reminders(*, settings=None, reminder_date: str | None = None, limit: int | None = None) -> dict[str, int]:
	"""Send reminders for active leases whose end date is approaching."""
	settings = settings or _get_settings()
	result = _empty_result()

	if not _is_enabled(settings, "auto_send_lease_expiry_reminder_sms"):
		return result

	reminder_date = reminder_date or nowdate()
	today = getdate(reminder_date)
	days_before = _parse_days(getattr(settings, "lease_expiry_reminder_days_before", None), "30,7,1")
	limit = limit or _safe_limit(settings)

	leases = frappe.get_all(
		"Lease Agreement",
		filters={"docstatus": 1, "status": "Active"},
		fields=[
			"name",
			"tenant",
			"tenant_name",
			"tenant_phone_number",
			"property",
			"property_name",
			"unit",
			"end_date",
		],
		order_by="end_date asc, tenant_name asc",
	)

	for lease in leases:
		if result["matched"] >= limit:
			break
		if not lease.get("end_date"):
			continue

		days_until_expiry = date_diff(getdate(lease.get("end_date")), today)
		if days_until_expiry not in days_before:
			continue

		result["matched"] += 1
		tenant = _get_tenant_details(lease)
		end_date = formatdate(lease.get("end_date"))
		property_label = _property_label(lease)
		property_text = f" for {property_label}" if property_label else ""

		fallback_message = (
			f"Dear {tenant['tenant_name']}, your lease {lease.name}{property_text} ends "
			f"{_format_days_text(days_until_expiry)} on {end_date}. "
			"Please contact management for renewal or handover arrangements."
		)
		context = {
			"tenant": tenant.get("tenant"),
			"tenant_name": tenant.get("tenant_name"),
			"lease_name": lease.name,
			"lease_agreement": lease.name,
			"property": lease.get("property"),
			"property_label": property_label,
			"unit": lease.get("unit"),
			"end_date": end_date,
			"days_until_expiry": days_until_expiry,
			"days_text": _format_days_text(days_until_expiry),
		}
		message, template_used = _render_configured_reminder_template(
			settings=settings,
			settings_fieldname="lease_expiry_reminder_sms_template",
			template_type=LEASE_EXPIRY_TEMPLATE,
			context=context,
			fallback_message=fallback_message,
		)

		_record_result(
			result,
			_send_reminder_sms(
				phone_number=tenant.get("phone_number"),
				message=message,
				reminder_type=LEASE_EXPIRY_REMINDER,
				reminder_date=reminder_date,
				recipient_doctype="Tenant" if tenant.get("tenant") else None,
				recipient_name=tenant.get("tenant"),
				reference_doctype="Lease Agreement",
				reference_name=lease.name,
				sms_template=template_used,
			),
		)

	return result


def run_daily_sms_reminders() -> dict[str, Any]:
	"""
	Daily scheduler entry point for automated SMS reminders.

	This is safe to call manually too. It respects all toggles in Rentals SMS Settings.
	"""
	settings = _get_settings()
	if not settings or not settings.enabled:
		return {"ok": True, "skipped": True, "reason": "SMS disabled or settings missing."}

	reminder_date = nowdate()
	limit = _safe_limit(settings)
	remaining = limit

	result: dict[str, Any] = {
		"ok": True,
		"reminder_date": reminder_date,
		"limit": limit,
		"rent_due": _empty_result(),
		"overdue_invoice": _empty_result(),
		"lease_expiry": _empty_result(),
	}

	if remaining > 0:
		result["rent_due"] = send_rent_due_reminders(settings=settings, reminder_date=reminder_date, limit=remaining)
		remaining -= result["rent_due"].get("matched", 0)

	if remaining > 0:
		result["overdue_invoice"] = send_overdue_invoice_reminders(settings=settings, reminder_date=reminder_date, limit=remaining)
		remaining -= result["overdue_invoice"].get("matched", 0)

	if remaining > 0:
		result["lease_expiry"] = send_lease_expiry_reminders(settings=settings, reminder_date=reminder_date, limit=remaining)
		remaining -= result["lease_expiry"].get("matched", 0)

	result["sent_total"] = (
		result["rent_due"].get("sent", 0)
		+ result["overdue_invoice"].get("sent", 0)
		+ result["lease_expiry"].get("sent", 0)
	)
	result["remaining_limit"] = remaining

	return result


@frappe.whitelist()
def run_sms_reminders(reminder_type: str | None = None) -> dict[str, Any]:
	"""Manual Desk/API helper for System Managers to run reminder jobs."""
	frappe.only_for("System Manager")

	settings = _get_settings()
	if not settings or not settings.enabled:
		return {"ok": True, "skipped": True, "reason": "SMS disabled or settings missing."}

	reminder_type = (reminder_type or "All").strip()
	reminder_date = nowdate()
	limit = _safe_limit(settings)

	if reminder_type in ("All", ""):
		return run_daily_sms_reminders()

	if reminder_type == RENT_DUE_REMINDER:
		return {"ok": True, "rent_due": send_rent_due_reminders(settings=settings, reminder_date=reminder_date, limit=limit)}

	if reminder_type == OVERDUE_INVOICE_REMINDER:
		return {"ok": True, "overdue_invoice": send_overdue_invoice_reminders(settings=settings, reminder_date=reminder_date, limit=limit)}

	if reminder_type == LEASE_EXPIRY_REMINDER:
		return {"ok": True, "lease_expiry": send_lease_expiry_reminders(settings=settings, reminder_date=reminder_date, limit=limit)}

	frappe.throw("Invalid reminder_type. Use All, Rent Due, Overdue Invoice, or Lease Expiry.")
