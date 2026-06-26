"""
Africa's Talking SMS integration for Rentals.

This module is intentionally the only place that talks to the provider SDK.
Other app features should call send_sms(...) or send_bulk_sms(...) instead of
importing africastalking directly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

import frappe
from frappe import _

from rentals.sms.preferences import can_send_sms_to_recipient
from rentals.sms.utils import (
	SMSValidationError,
	get_default_country_code,
	normalize_recipients,
	normalize_sms_message,
)

SMS_SETTINGS_DOCTYPE = "Rentals SMS Settings"
SMS_LOG_DOCTYPE = "Rentals SMS Log"


@dataclass(slots=True)
class SMSRecipientResult:
	phone_number: str
	status: str
	message_id: str | None = None
	cost: str | None = None
	error: str | None = None
	log_name: str | None = None

	def as_dict(self) -> dict[str, Any]:
		return {
			"phone_number": self.phone_number,
			"status": self.status,
			"message_id": self.message_id,
			"cost": self.cost,
			"error": self.error,
			"log_name": self.log_name,
		}


def _get_settings():
	"""Load SMS settings or fail with a clear setup error."""
	if not frappe.db.exists("DocType", SMS_SETTINGS_DOCTYPE):
		frappe.throw(_("Rentals SMS Settings has not been installed. Run bench migrate."))

	settings = frappe.get_single(SMS_SETTINGS_DOCTYPE)
	if not settings.enabled:
		frappe.throw(_("SMS is disabled in Rentals SMS Settings."))

	if not settings.username:
		frappe.throw(_("Africa's Talking username is required in Rentals SMS Settings."))

	api_key = settings.get_password("api_key") if hasattr(settings, "get_password") else settings.api_key
	if not api_key:
		frappe.throw(_("Africa's Talking API key is required in Rentals SMS Settings."))

	return settings, api_key


def _get_sms_client(settings, api_key: str):
	"""Initialize and return the Africa's Talking SMS service."""
	try:
		import africastalking
	except ImportError:
		frappe.throw(_("Africa's Talking SDK is not installed. Run: bench pip install africastalking~=2.0.2"))

	africastalking.initialize(settings.username, api_key)
	return africastalking.SMS


def _json_dumps(value: Any) -> str:
	try:
		return json.dumps(value, default=str, ensure_ascii=False)
	except Exception:
		return str(value)


def _create_sms_log(
	*,
	recipient_phone: str,
	normalized_phone: str,
	message: str,
	status: str,
	recipient_doctype: str | None = None,
	recipient_name: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	sms_campaign: str | None = None,
	sms_category: str | None = "Transactional",
	sms_template: str | None = None,
	reminder_type: str | None = None,
	reminder_date: str | None = None,
	provider_message_id: str | None = None,
	provider_cost: str | None = None,
	provider_response: Any | None = None,
	error: str | None = None,
):
	"""Create one SMS log row. Logging failures should not hide the send result."""
	try:
		log = frappe.get_doc({
			"doctype": SMS_LOG_DOCTYPE,
			"recipient_phone": recipient_phone,
			"normalized_phone": normalized_phone,
			"recipient_doctype": recipient_doctype,
			"recipient_name": recipient_name,
			"message": message,
			"status": status,
			"provider_message_id": provider_message_id,
			"provider_cost": provider_cost,
			"provider_response": _json_dumps(provider_response) if provider_response is not None else None,
			"error": error,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"sms_campaign": sms_campaign,
			"sms_category": sms_category,
			"sms_template": sms_template,
			"reminder_type": reminder_type,
			"reminder_date": reminder_date,
		})
		log.insert(ignore_permissions=True)
		return log
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Log Creation Error")
		return None


def _update_sms_log(log_name: str | None, **values):
	"""Update an SMS log if it exists."""
	if not log_name:
		return

	try:
		clean_values = {key: value for key, value in values.items() if value is not None}
		if clean_values:
			frappe.db.set_value(SMS_LOG_DOCTYPE, log_name, clean_values, update_modified=True)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Log Update Error")


def _extract_recipient_results(
	*,
	response: Any,
	normalized_recipients: list[str],
	logs_by_phone: dict[str, str | None],
) -> list[SMSRecipientResult]:
	"""Map provider response recipients into stable app-level result objects."""
	try:
		data = response or {}
		sms_data = data.get("SMSMessageData") or {}
		recipients = sms_data.get("Recipients") or []
	except Exception:
		recipients = []

	results: list[SMSRecipientResult] = []
	seen: set[str] = set()

	for recipient in recipients:
		phone = recipient.get("number") or recipient.get("phoneNumber")
		status = recipient.get("status") or "Submitted"
		message_id = recipient.get("messageId") or recipient.get("message_id")
		cost = recipient.get("cost")
		error = recipient.get("errorMessage") or recipient.get("error")

		if not phone:
			continue

		seen.add(phone)
		log_name = logs_by_phone.get(phone)
		_update_sms_log(
			log_name,
			status=status,
			provider_message_id=message_id,
			provider_cost=cost,
			provider_response=_json_dumps(response),
			error=error,
		)

		results.append(SMSRecipientResult(
			phone_number=phone,
			status=status,
			message_id=message_id,
			cost=cost,
			error=error,
			log_name=log_name,
		))

	# Some provider errors may not return per-recipient data.
	for phone in normalized_recipients:
		if phone in seen:
			continue

		log_name = logs_by_phone.get(phone)
		_update_sms_log(log_name, status="Submitted", provider_response=_json_dumps(response))
		results.append(SMSRecipientResult(
			phone_number=phone,
			status="Submitted",
			log_name=log_name,
		))

	return results


def send_sms(
	*,
	recipients: str | int | Iterable[str | int],
	message: str,
	recipient_doctype: str | None = None,
	recipient_name: str | None = None,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	sms_campaign: str | None = None,
	sms_category: str | None = "Transactional",
	sms_template: str | None = None,
	reminder_type: str | None = None,
	reminder_date: str | None = None,
	sender_id: str | None = None,
	enqueue: bool | None = None,
) -> dict[str, Any]:
	"""
	Send an SMS to one or more recipients and create one SMS Log per recipient.

	Use this for test sends, transactional sends, and chunked campaign sends.
	"""
	settings, api_key = _get_settings()
	default_country_code = settings.default_country_code or get_default_country_code()
	message = normalize_sms_message(message)
	normalized_recipients = normalize_recipients(recipients, default_country_code=default_country_code)

	resolved_sender_id = sender_id if sender_id is not None else settings.sender_id
	resolved_enqueue = bool(settings.enqueue if enqueue is None else enqueue)

	allowed, block_reason = can_send_sms_to_recipient(
		recipient_doctype=recipient_doctype,
		recipient_name=recipient_name,
		sms_category=sms_category,
		settings=settings,
	)

	logs_by_phone: dict[str, str | None] = {}
	if not allowed:
		results: list[SMSRecipientResult] = []
		for phone in normalized_recipients:
			log = _create_sms_log(
				recipient_phone=phone,
				normalized_phone=phone,
				message=message,
				status="OptedOut",
				recipient_doctype=recipient_doctype,
				recipient_name=recipient_name,
				reference_doctype=reference_doctype,
				reference_name=reference_name,
				sms_campaign=sms_campaign,
				sms_category=sms_category,
				sms_template=sms_template,
				reminder_type=reminder_type,
				reminder_date=reminder_date,
				error=block_reason,
			)
			results.append(SMSRecipientResult(
				phone_number=phone,
				status="OptedOut",
				error=block_reason,
				log_name=log.name if log else None,
			))

		return {
			"ok": True,
			"skipped": True,
			"message": block_reason or "SMS skipped.",
			"provider": "Africa's Talking",
			"recipients": [result.as_dict() for result in results],
			"provider_response": None,
		}

	for phone in normalized_recipients:
		log = _create_sms_log(
			recipient_phone=phone,
			normalized_phone=phone,
			message=message,
			status="Queued" if resolved_enqueue else "Pending",
			recipient_doctype=recipient_doctype,
			recipient_name=recipient_name,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			sms_campaign=sms_campaign,
			sms_category=sms_category,
			sms_template=sms_template,
			reminder_type=reminder_type,
			reminder_date=reminder_date,
		)
		logs_by_phone[phone] = log.name if log else None

	try:
		sms = _get_sms_client(settings, api_key)
		response = sms.send(
			message,
			normalized_recipients,
			resolved_sender_id or None,
			resolved_enqueue,
		)

		results = _extract_recipient_results(
			response=response,
			normalized_recipients=normalized_recipients,
			logs_by_phone=logs_by_phone,
		)

		return {
			"ok": True,
			"message": "SMS submitted successfully.",
			"provider": "Africa's Talking",
			"recipients": [result.as_dict() for result in results],
			"provider_response": response,
		}

	except SMSValidationError:
		raise
	except Exception as exc:
		error = str(exc)
		for phone, log_name in logs_by_phone.items():
			_update_sms_log(log_name, status="Failed", error=error)

		frappe.log_error(frappe.get_traceback(), "Africa's Talking SMS Send Error")
		frappe.throw(_("Failed to send SMS: {0}").format(error))


def send_bulk_sms(
	*,
	recipients: Iterable[str | int],
	message: str,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	sms_campaign: str | None = None,
	sms_category: str | None = "Campaign",
	sms_template: str | None = None,
	reminder_type: str | None = None,
	reminder_date: str | None = None,
	sender_id: str | None = None,
	enqueue: bool | None = True,
) -> dict[str, Any]:
	"""
	Bulk-capable wrapper used by SMS campaigns.

	Campaigns call this in chunks so provider/network failures do not block the
	Desk request that started the campaign.
	"""
	return send_sms(
		recipients=recipients,
		message=message,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		sms_campaign=sms_campaign,
		sms_category=sms_category,
		sms_template=sms_template,
		reminder_type=reminder_type,
		reminder_date=reminder_date,
		sender_id=sender_id,
		enqueue=enqueue,
	)
