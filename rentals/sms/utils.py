"""
SMS utility helpers for Rentals.

Currently handles:
- phone number cleanup
- E.164-style normalization for Africa's Talking
- safe message normalization
"""

from __future__ import annotations

import re
from typing import Iterable

import frappe
from frappe import _

_DIGITS_ONLY_RE = re.compile(r"\D+")


class SMSValidationError(ValueError):
	"""Raised when an SMS input cannot be safely sent."""


def clean_phone_number(phone_number: str | int | None) -> str:
	"""Return a compact phone string without spaces, dashes, or brackets."""
	if phone_number is None:
		return ""

	phone = str(phone_number).strip()
	if not phone:
		return ""

	# Keep a leading + if present, then strip every other non-digit character.
	if phone.startswith("+"):
		return "+" + _DIGITS_ONLY_RE.sub("", phone[1:])

	return _DIGITS_ONLY_RE.sub("", phone)


def normalize_phone_number(
	phone_number: str | int | None,
	*,
	default_country_code: str | int | None = "254",
) -> str:
	"""
	Normalize local or international numbers for Africa's Talking.

	Examples using the default Kenya country code:
	- 0712345678     -> +254712345678
	- 254712345678   -> +254712345678
	- +254712345678  -> +254712345678
	"""
	phone = clean_phone_number(phone_number)
	country_code = clean_phone_number(default_country_code or "254").lstrip("+")

	if not phone:
		raise SMSValidationError(_("Phone number is required."))

	if phone.startswith("+"):
		digits = phone[1:]
		if len(digits) < 8 or len(digits) > 15:
			raise SMSValidationError(_("Phone number must be in a valid international format."))
		return f"+{digits}"

	if phone.startswith("00"):
		digits = phone[2:]
		if len(digits) < 8 or len(digits) > 15:
			raise SMSValidationError(_("Phone number must be in a valid international format."))
		return f"+{digits}"

	if country_code and phone.startswith(country_code):
		digits = phone
	elif country_code and phone.startswith("0"):
		digits = f"{country_code}{phone[1:]}"
	elif country_code and len(phone) <= 10:
		# Handles user input like 712345678.
		digits = f"{country_code}{phone}"
	else:
		digits = phone

	if len(digits) < 8 or len(digits) > 15:
		raise SMSValidationError(_("Phone number must be between 8 and 15 digits after normalization."))

	return f"+{digits}"


def normalize_recipients(
	recipients: str | int | Iterable[str | int],
	*,
	default_country_code: str | int | None = "254",
) -> list[str]:
	"""Normalize, deduplicate, and return recipient phone numbers."""
	if isinstance(recipients, (str, int)):
		recipient_values = [recipients]
	else:
		recipient_values = list(recipients or [])

	seen: set[str] = set()
	normalized: list[str] = []

	for recipient in recipient_values:
		phone = normalize_phone_number(recipient, default_country_code=default_country_code)
		if phone not in seen:
			seen.add(phone)
			normalized.append(phone)

	if not normalized:
		raise SMSValidationError(_("At least one valid recipient phone number is required."))

	return normalized


def normalize_sms_message(message: str | None, *, max_length: int = 918) -> str:
	"""
	Normalize an SMS message and enforce a sane upper length.

	918 characters allows up to six GSM multipart segments. This avoids accidental
	very large sends while still allowing useful operational messages.
	"""
	message = (message or "").strip()
	if not message:
		raise SMSValidationError(_("SMS message is required."))

	if len(message) > max_length:
		raise SMSValidationError(_("SMS message is too long. Maximum allowed length is {0} characters.").format(max_length))

	return message


def get_default_country_code() -> str:
	"""Return country code from SMS Settings, falling back to Kenya."""
	try:
		if frappe.db.exists("DocType", "Rentals SMS Settings"):
			value = frappe.db.get_single_value("Rentals SMS Settings", "default_country_code")
			return clean_phone_number(value or "254").lstrip("+") or "254"
	except Exception:
		# During install/migrate the Single doctype may not exist yet.
		pass

	return "254"
