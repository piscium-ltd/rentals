"""
SMS recipient preference helpers for Rentals.

Handles opt-out checks for Tenant and Landlord records so transactional,
reminder, and campaign sends can make one consistent allow/skip decision.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cint, now_datetime

SMS_SETTINGS_DOCTYPE = "Rentals SMS Settings"
OPT_OUT_CAPABLE_DOCTYPES = {"Tenant", "Landlord"}
CAMPAIGN_CATEGORIES = {"Campaign", "Bulk Campaign", "Marketing"}
TRANSACTIONAL_CATEGORIES = {"Transactional", "Reminder", "Test", "Callback", "Other"}


def get_sms_settings():
	"""Return SMS settings, or None during install/migrate."""
	try:
		if frappe.db.exists("DocType", SMS_SETTINGS_DOCTYPE):
			return frappe.get_single(SMS_SETTINGS_DOCTYPE)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Preference Settings Error")
	return None


def _is_enabled(value: Any, default: bool = False) -> bool:
	if value in (None, ""):
		return default
	return bool(cint(value))


def is_recipient_opted_out(recipient_doctype: str | None, recipient_name: str | None) -> bool:
	"""Return True when the linked recipient has Allow SMS unchecked."""
	if not recipient_doctype or not recipient_name:
		return False
	if recipient_doctype not in OPT_OUT_CAPABLE_DOCTYPES:
		return False

	try:
		allow_sms = frappe.db.get_value(recipient_doctype, recipient_name, "allow_sms")
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Opt-out Lookup Error")
		return False

	# Existing records may not have a value yet; treat missing as allowed.
	if allow_sms in (None, ""):
		return False

	return not bool(cint(allow_sms))


def can_send_sms_to_recipient(
	*,
	recipient_doctype: str | None = None,
	recipient_name: str | None = None,
	sms_category: str | None = "Transactional",
	settings=None,
) -> tuple[bool, str | None]:
	"""
	Return (allowed, reason) for a recipient.

	Campaign SMS is skipped for opted-out tenants/landlords by default.
	Transactional/reminder SMS can still be allowed by settings because they are
	operational messages like invoices, payments, and lease notices.
	"""
	settings = settings or get_sms_settings()
	if not settings:
		return True, None

	if not _is_enabled(getattr(settings, "respect_recipient_sms_opt_out", 1), default=True):
		return True, None

	if not is_recipient_opted_out(recipient_doctype, recipient_name):
		return True, None

	category = (sms_category or "Transactional").strip()
	if category in CAMPAIGN_CATEGORIES:
		if _is_enabled(getattr(settings, "send_campaign_sms_to_opted_out_recipients", 0), default=False):
			return True, None
		return False, "Recipient has opted out of campaign SMS."

	if category in TRANSACTIONAL_CATEGORIES:
		if _is_enabled(getattr(settings, "send_transactional_sms_to_opted_out_recipients", 1), default=True):
			return True, None
		return False, "Recipient has opted out of SMS."

	return False, "Recipient has opted out of SMS."



def _doctype_phone_fields(doctype: str) -> list[str]:
	"""Return phone fields that exist on the doctype."""
	candidates = {
		"Tenant": ["phone_number", "mobile_no"],
		"Landlord": ["mobile_no", "phone_number"],
	}.get(doctype, [])
	try:
		meta = frappe.get_meta(doctype)
		return [fieldname for fieldname in candidates if meta.has_field(fieldname)]
	except Exception:
		return candidates


def find_sms_recipients_by_phone(phone_number: str | None) -> list[dict[str, Any]]:
	"""Find Tenant/Landlord records whose phone fields match the supplied phone."""
	if not phone_number:
		return []

	from rentals.sms.utils import SMSValidationError, get_default_country_code, normalize_phone_number

	try:
		target_phone = normalize_phone_number(phone_number, default_country_code=get_default_country_code())
	except SMSValidationError:
		return []

	matches: list[dict[str, Any]] = []
	seen: set[tuple[str, str]] = set()

	for doctype in ("Tenant", "Landlord"):
		phone_fields = _doctype_phone_fields(doctype)
		if not phone_fields:
			continue

		fields = ["name"]
		for optional_field in ("full_name", "company_name", "status"):
			try:
				if frappe.get_meta(doctype).has_field(optional_field):
					fields.append(optional_field)
			except Exception:
				pass
		fields.extend(phone_fields)

		try:
			rows = frappe.get_all(doctype, fields=list(dict.fromkeys(fields)))
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Rentals SMS Recipient Lookup Error: {doctype}")
			continue

		for row in rows:
			for phone_field in phone_fields:
				value = row.get(phone_field)
				if not value:
					continue
				try:
					normalized = normalize_phone_number(value, default_country_code=get_default_country_code())
				except SMSValidationError:
					continue
				if normalized != target_phone:
					continue

				key = (doctype, row.get("name"))
				if key in seen:
					continue
				seen.add(key)
				matches.append({
					"doctype": doctype,
					"name": row.get("name"),
					"display_name": row.get("full_name") or row.get("company_name") or row.get("name"),
					"phone_field": phone_field,
					"phone_number": value,
					"normalized_phone": normalized,
				})
				break

	return matches


def set_sms_preference_for_recipient(
	*,
	recipient_doctype: str | None,
	recipient_name: str | None,
	allow_sms: bool,
	reason: str | None = None,
) -> None:
	"""Update Allow SMS fields on a Tenant/Landlord record."""
	if not recipient_doctype or not recipient_name:
		return
	if recipient_doctype not in OPT_OUT_CAPABLE_DOCTYPES:
		return

	updates = {"allow_sms": 1 if allow_sms else 0}
	try:
		meta = frappe.get_meta(recipient_doctype)
		if meta.has_field("sms_opt_out_reason"):
			updates["sms_opt_out_reason"] = None if allow_sms else reason
		if meta.has_field("sms_opt_out_on"):
			updates["sms_opt_out_on"] = None if allow_sms else now_datetime()
		frappe.db.set_value(recipient_doctype, recipient_name, updates, update_modified=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Preference Update Error")
		raise
