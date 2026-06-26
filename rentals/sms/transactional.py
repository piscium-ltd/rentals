"""
Transactional SMS helpers for Rentals.

This module is the bridge between business events and the Africa's Talking
service wrapper. Business code should call these helpers instead of formatting
and sending SMS directly.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt, formatdate

from rentals.sms.africas_talking import SMS_SETTINGS_DOCTYPE, send_sms
from rentals.sms.templates import render_sms_template


SMS_QUEUE = "short"


LEASE_CREATED_TEMPLATE = "Lease Created"
INVOICE_CREATED_TEMPLATE = "Invoice Created"
PAYMENT_RECEIVED_TEMPLATE = "Payment Received"


def _get_settings():
	"""Return Rentals SMS Settings, or None when the doctype is not installed yet."""
	try:
		if not frappe.db.exists("DocType", SMS_SETTINGS_DOCTYPE):
			return None
		return frappe.get_single(SMS_SETTINGS_DOCTYPE)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Settings Lookup Error")
		return None


def _get_enabled_settings(fieldname: str):
	"""Return settings only when global SMS and the requested automation toggle are enabled."""
	settings = _get_settings()
	if not settings:
		return None
	return settings if settings.enabled and getattr(settings, fieldname, 0) else None


def _format_money(currency: str | None, amount: float | int | str | None) -> str:
	"""Return a compact money string for SMS."""
	currency = currency or "KES"
	value = flt(amount)

	if value == int(value):
		return f"{currency} {int(value):,}"

	return f"{currency} {value:,.2f}"


def _first_present(*values: Any) -> Any | None:
	"""Return the first non-empty value."""
	for value in values:
		if value not in (None, ""):
			return value
	return None


def _get_tenant_phone(lease_doc) -> str | None:
	"""Resolve the best tenant phone number from the lease and linked tenant."""
	phone = getattr(lease_doc, "tenant_phone_number", None)
	if phone:
		return phone

	if getattr(lease_doc, "tenant", None):
		return _first_present(
			frappe.db.get_value("Tenant", lease_doc.tenant, "phone_number"),
			frappe.db.get_value("Tenant", lease_doc.tenant, "mobile_no"),
		)

	return None


def _get_tenant_name(lease_doc) -> str:
	"""Resolve a readable tenant name for SMS."""
	return _first_present(
		getattr(lease_doc, "tenant_name", None),
		frappe.db.get_value("Tenant", getattr(lease_doc, "tenant", None), "full_name") if getattr(lease_doc, "tenant", None) else None,
		getattr(lease_doc, "customer", None),
		"Tenant",
	)


def _get_property_label(lease_doc) -> str | None:
	"""Resolve a readable property/unit label for SMS."""
	property_name = _first_present(
		getattr(lease_doc, "property_name", None),
		getattr(lease_doc, "property", None),
	)
	unit = getattr(lease_doc, "unit", None)

	if property_name and unit:
		return f"{property_name}, Unit {unit}"
	if property_name:
		return str(property_name)
	if unit:
		return f"Unit {unit}"
	return None


def _lease_context(lease_doc, **extra) -> dict[str, Any]:
	"""Common template context for lease-linked transactional SMS."""
	context = {
		"tenant": getattr(lease_doc, "tenant", None),
		"tenant_name": _get_tenant_name(lease_doc),
		"tenant_phone_number": _get_tenant_phone(lease_doc),
		"lease_name": getattr(lease_doc, "name", None),
		"lease_agreement": getattr(lease_doc, "name", None),
		"property": getattr(lease_doc, "property", None),
		"property_name": getattr(lease_doc, "property_name", None),
		"unit": getattr(lease_doc, "unit", None),
		"property_label": _get_property_label(lease_doc),
		"currency": getattr(lease_doc, "billing_currency", None) or "KES",
		"account_number": getattr(lease_doc, "name", None),
	}
	context.update(extra)
	return context


def _render_configured_template(
	*,
	settings,
	settings_fieldname: str,
	template_type: str,
	context: dict[str, Any],
	fallback_message: str,
) -> tuple[str, str | None]:
	"""Render configured template from settings, falling back to the built-in message."""
	return render_sms_template(
		template_name=getattr(settings, settings_fieldname, None),
		template_type=template_type,
		context=context,
		fallback_message=fallback_message,
	)


def _enqueue_transactional_sms(
	*,
	phone_number: str | None,
	message: str,
	recipient_doctype: str | None = None,
	recipient_name: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	sms_template: str | None = None,
) -> dict[str, Any]:
	"""
	Queue a transactional SMS without blocking the current request/submit flow.

	The worker uses send_transactional_sms(), which creates the SMS Log and calls
	Africa's Talking through the central provider wrapper.
	"""
	if not phone_number:
		return {"ok": False, "skipped": True, "reason": "Missing recipient phone number."}

	try:
		frappe.enqueue(
			"rentals.sms.transactional.send_transactional_sms",
			queue=SMS_QUEUE,
			enqueue_after_commit=True,
			phone_number=phone_number,
			message=message,
			recipient_doctype=recipient_doctype,
			recipient_name=recipient_name,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			sms_template=sms_template,
		)
		return {"ok": True, "queued": True}
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals Transactional SMS Queue Error")
		return {"ok": False, "queued": False}


def send_transactional_sms(
	*,
	phone_number: str,
	message: str,
	recipient_doctype: str | None = None,
	recipient_name: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	sms_template: str | None = None,
) -> dict[str, Any] | None:
	"""Worker-safe function used by queued transactional SMS jobs."""
	try:
		return send_sms(
			recipients=phone_number,
			message=message,
			recipient_doctype=recipient_doctype,
			recipient_name=recipient_name,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			sms_category="Transactional",
			sms_template=sms_template,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals Transactional SMS Send Error")
		return None


def send_lease_created_sms(lease_doc) -> dict[str, Any] | None:
	"""Queue lease creation/payment instruction SMS for the tenant."""
	if getattr(lease_doc, "get", None) and lease_doc.get("__is_duplicate"):
		return None

	settings = _get_enabled_settings("auto_send_lease_sms")
	if not settings:
		return None

	tenant_phone = _get_tenant_phone(lease_doc)
	currency = getattr(lease_doc, "billing_currency", None) or "KES"
	amount = _format_money(currency, getattr(lease_doc, "grand_total", None))
	property_label = _get_property_label(lease_doc)

	context = _lease_context(
		lease_doc,
		amount=amount,
		grand_total=getattr(lease_doc, "grand_total", None),
	)

	message_parts = [
		f"Dear {context['tenant_name']}, your lease {lease_doc.name} has been created.",
	]

	if property_label:
		message_parts.append(f"Property: {property_label}.")

	message_parts.append(f"Amount due: {amount}.")
	message_parts.append(f"Use account number {lease_doc.name} when paying rent.")
	fallback_message = " ".join(message_parts)
	message, template_used = _render_configured_template(
		settings=settings,
		settings_fieldname="lease_sms_template",
		template_type=LEASE_CREATED_TEMPLATE,
		context=context,
		fallback_message=fallback_message,
	)

	return _enqueue_transactional_sms(
		phone_number=tenant_phone,
		message=message,
		recipient_doctype="Tenant" if getattr(lease_doc, "tenant", None) else None,
		recipient_name=getattr(lease_doc, "tenant", None),
		reference_doctype="Lease Agreement",
		reference_name=lease_doc.name,
		sms_template=template_used,
	)


def send_invoice_created_sms(lease_doc, invoice_doc) -> dict[str, Any] | None:
	"""Queue invoice notification SMS for the tenant."""
	settings = _get_enabled_settings("auto_send_invoice_sms")
	if not settings:
		return None

	tenant_phone = _get_tenant_phone(lease_doc)
	currency = getattr(invoice_doc, "currency", None) or getattr(lease_doc, "billing_currency", None) or "KES"
	amount = _format_money(currency, getattr(invoice_doc, "grand_total", None))
	due_date = formatdate(getattr(invoice_doc, "due_date", None)) if getattr(invoice_doc, "due_date", None) else None
	due_text = f" Due date: {due_date}." if due_date else ""

	context = _lease_context(
		lease_doc,
		invoice_name=getattr(invoice_doc, "name", None),
		invoice=getattr(invoice_doc, "name", None),
		amount=amount,
		grand_total=getattr(invoice_doc, "grand_total", None),
		due_date=due_date,
	)

	fallback_message = (
		f"Dear {context['tenant_name']}, invoice {invoice_doc.name} for {amount} has been generated "
		f"for lease {lease_doc.name}.{due_text} Pay using account number {lease_doc.name}."
	)
	message, template_used = _render_configured_template(
		settings=settings,
		settings_fieldname="invoice_sms_template",
		template_type=INVOICE_CREATED_TEMPLATE,
		context=context,
		fallback_message=fallback_message,
	)

	return _enqueue_transactional_sms(
		phone_number=tenant_phone,
		message=message,
		recipient_doctype="Tenant" if getattr(lease_doc, "tenant", None) else None,
		recipient_name=getattr(lease_doc, "tenant", None),
		reference_doctype="Sales Invoice",
		reference_name=invoice_doc.name,
		sms_template=template_used,
	)


def send_payment_received_sms(
	*,
	lease_name: str,
	amount: float | int | str,
	mpesa_receipt: str | None = None,
	payer_phone: str | None = None,
	payment_entry: str | None = None,
) -> dict[str, Any] | None:
	"""Queue M-Pesa payment confirmation SMS for the tenant/payer."""
	settings = _get_enabled_settings("auto_send_payment_sms")
	if not settings:
		return None

	try:
		lease_doc = frappe.get_doc("Lease Agreement", lease_name)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals Payment SMS Lease Lookup Error")
		return None

	tenant_phone = _first_present(_get_tenant_phone(lease_doc), payer_phone)
	currency = getattr(lease_doc, "billing_currency", None) or "KES"
	amount_text = _format_money(currency, amount)
	receipt_text = f" Receipt: {mpesa_receipt}." if mpesa_receipt else ""

	context = _lease_context(
		lease_doc,
		amount=amount_text,
		paid_amount=amount,
		mpesa_receipt=mpesa_receipt,
		payer_phone=payer_phone,
		payment_entry=payment_entry,
	)

	fallback_message = (
		f"Dear {context['tenant_name']}, payment of {amount_text} for lease {lease_doc.name} has been received."
		f"{receipt_text} Thank you."
	)
	message, template_used = _render_configured_template(
		settings=settings,
		settings_fieldname="payment_sms_template",
		template_type=PAYMENT_RECEIVED_TEMPLATE,
		context=context,
		fallback_message=fallback_message,
	)

	return _enqueue_transactional_sms(
		phone_number=tenant_phone,
		message=message,
		recipient_doctype="Tenant" if getattr(lease_doc, "tenant", None) else None,
		recipient_name=getattr(lease_doc, "tenant", None),
		reference_doctype="Payment Entry" if payment_entry else "Lease Agreement",
		reference_name=payment_entry or lease_doc.name,
		sms_template=template_used,
	)
