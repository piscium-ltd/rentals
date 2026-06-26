"""
Africa's Talking delivery-report callbacks for Rentals SMS.

This module receives provider delivery reports and updates:
- Rentals SMS Log
- Rentals SMS Campaign Recipient, when the SMS belongs to a campaign
- Rentals SMS Campaign totals
"""

from __future__ import annotations

import hmac
import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from rentals.sms.africas_talking import SMS_LOG_DOCTYPE, SMS_SETTINGS_DOCTYPE
from rentals.sms.campaign import (
	FAILED_STATUSES,
	SENT_STATUSES,
	SMS_CAMPAIGN_RECIPIENT_DOCTYPE,
	update_campaign_totals,
)
from rentals.sms.utils import SMSValidationError, get_default_country_code, normalize_phone_number

DELIVERY_SUCCESS_STATUSES = {
	"Success",
	"Sent",
	"Submitted",
	"Buffered",
	"Delivered",
}

DELIVERY_FAILED_STATUSES = {
	"Failed",
	"Rejected",
	"InvalidPhoneNumber",
	"InsufficientBalance",
	"UserInBlacklist",
	"NotSent",
	"Expired",
}

ALLOWED_LOG_STATUSES = SENT_STATUSES | FAILED_STATUSES | DELIVERY_SUCCESS_STATUSES | DELIVERY_FAILED_STATUSES | {
	"Pending",
	"Queued",
	"Expired",
}

STATUS_ALIASES = {
	"success": "Success",
	"sent": "Sent",
	"submitted": "Submitted",
	"buffered": "Buffered",
	"delivered": "Delivered",
	"failed": "Failed",
	"failure": "Failed",
	"rejected": "Rejected",
	"invalidphonenumber": "InvalidPhoneNumber",
	"invalid phone number": "InvalidPhoneNumber",
	"insufficientbalance": "InsufficientBalance",
	"insufficient balance": "InsufficientBalance",
	"userinblacklist": "UserInBlacklist",
	"user in blacklist": "UserInBlacklist",
	"not sent": "NotSent",
	"notsent": "NotSent",
	"expired": "Expired",
}


def _json_dumps(value: Any) -> str:
	try:
		return json.dumps(value, default=str, ensure_ascii=False)
	except Exception:
		return str(value)


def _get_request_payload() -> dict[str, Any]:
	"""Return callback payload from form data, JSON body, or request args."""
	payload: dict[str, Any] = {}

	try:
		form_dict = dict(frappe.local.form_dict or {})
		payload.update({key: value for key, value in form_dict.items() if value not in (None, "")})
	except Exception:
		pass

	try:
		json_payload = frappe.request.get_json(silent=True) if getattr(frappe, "request", None) else None
		if isinstance(json_payload, dict):
			payload.update({key: value for key, value in json_payload.items() if value not in (None, "")})
	except Exception:
		pass

	try:
		args_payload = dict(frappe.request.args or {}) if getattr(frappe, "request", None) else {}
		payload.update({key: value for key, value in args_payload.items() if value not in (None, "")})
	except Exception:
		pass

	return payload


def _first_present(payload: dict[str, Any], *keys: str) -> Any | None:
	for key in keys:
		value = payload.get(key)
		if value not in (None, ""):
			return value
	return None


def _header_value(*keys: str) -> str | None:
	for key in keys:
		try:
			value = frappe.get_request_header(key)
		except Exception:
			value = None
		if value:
			return value
	return None


def _get_callback_secret_from_settings() -> str | None:
	try:
		settings = frappe.get_single(SMS_SETTINGS_DOCTYPE)
		secret = settings.get_password("delivery_callback_secret") if hasattr(settings, "get_password") else settings.delivery_callback_secret
		return secret or None
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Callback Settings Error")
		return None


def _validate_callback_secret(payload: dict[str, Any]) -> None:
	"""
	Validate optional callback secret.

	When the secret is blank in Rentals SMS Settings, callbacks are accepted. Once
	configured, the provider callback URL must pass it as ?secret=..., ?key=..., or
	in X-Rentals-SMS-Callback-Secret / X-AT-Callback-Secret header.
	"""
	configured_secret = _get_callback_secret_from_settings()
	if not configured_secret:
		return

	provided_secret = (
		_first_present(payload, "secret", "key", "callback_secret", "delivery_callback_secret")
		or _header_value("X-Rentals-SMS-Callback-Secret", "X-AT-Callback-Secret")
	)

	if not provided_secret or not hmac.compare_digest(str(provided_secret), str(configured_secret)):
		frappe.throw(_("Invalid SMS delivery callback secret."), frappe.PermissionError)


def _normalize_callback_status(status: str | None) -> str:
	if not status:
		return "Submitted"

	status_text = str(status).strip()
	alias = STATUS_ALIASES.get(status_text.lower())
	if alias:
		return alias

	# Preserve valid custom capitalization only if it is already supported by the DocType.
	if status_text in ALLOWED_LOG_STATUSES:
		return status_text

	# Avoid Select-field save errors for unknown provider statuses.
	return "Submitted"


def _normalize_callback_phone(phone_number: str | None) -> str | None:
	if not phone_number:
		return None
	try:
		return normalize_phone_number(
			phone_number,
			default_country_code=get_default_country_code(),
		)
	except SMSValidationError:
		return str(phone_number)


def _find_sms_log(message_id: str | None, normalized_phone: str | None) -> str | None:
	"""Find the most likely SMS Log for this delivery report."""
	if message_id:
		log_name = frappe.db.get_value(SMS_LOG_DOCTYPE, {"provider_message_id": message_id}, "name")
		if log_name:
			return log_name

	if normalized_phone:
		rows = frappe.get_all(
			SMS_LOG_DOCTYPE,
			filters={"normalized_phone": normalized_phone},
			fields=["name"],
			order_by="creation desc",
			limit=1,
		)
		if rows:
			return rows[0].name

	return None


def _update_sms_log_from_callback(
	*,
	log_name: str,
	payload: dict[str, Any],
	message_id: str | None,
	status: str,
	normalized_phone: str | None,
	provider_status: str | None,
	cost: str | None,
	network_code: str | None,
	failure_reason: str | None,
) -> dict[str, Any]:
	"""Update SMS Log and return the refreshed lightweight log row."""
	updates = {
		"status": status,
		"provider_delivery_status": provider_status,
		"provider_message_id": message_id,
		"provider_cost": cost,
		"network_code": network_code,
		"failure_reason": failure_reason,
		"delivery_report_payload": _json_dumps(payload),
		"delivery_report_received_on": now_datetime(),
	}

	if normalized_phone:
		updates["normalized_phone"] = normalized_phone

	if status in DELIVERY_FAILED_STATUSES or status in FAILED_STATUSES:
		updates["error"] = failure_reason or provider_status or status
	elif status in DELIVERY_SUCCESS_STATUSES or status in SENT_STATUSES:
		updates["error"] = None

	clean_updates = {key: value for key, value in updates.items() if value is not None}
	frappe.db.set_value(SMS_LOG_DOCTYPE, log_name, clean_updates, update_modified=True)

	return frappe.db.get_value(
		SMS_LOG_DOCTYPE,
		log_name,
		["name", "normalized_phone", "sms_campaign"],
		as_dict=True,
	) or {"name": log_name}


def _update_campaign_recipient_from_log(log: dict[str, Any], status: str, failure_reason: str | None) -> str | None:
	"""Update campaign child row linked to the SMS Log, if any."""
	campaign_name = log.get("sms_campaign")
	log_name = log.get("name")
	phone = log.get("normalized_phone")
	if not campaign_name:
		return None

	row_name = None
	if log_name:
		row_name = frappe.db.get_value(
			SMS_CAMPAIGN_RECIPIENT_DOCTYPE,
			{"parent": campaign_name, "sms_log": log_name},
			"name",
		)

	if not row_name and phone:
		row_name = frappe.db.get_value(
			SMS_CAMPAIGN_RECIPIENT_DOCTYPE,
			{"parent": campaign_name, "normalized_phone": phone},
			"name",
		)

	if not row_name:
		return None

	updates = {
		"status": status,
		"error": failure_reason if status in DELIVERY_FAILED_STATUSES or status in FAILED_STATUSES else None,
	}
	frappe.db.set_value(SMS_CAMPAIGN_RECIPIENT_DOCTYPE, row_name, updates, update_modified=True)

	try:
		update_campaign_totals(campaign_name)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Campaign Totals Callback Error")

	return row_name


@frappe.whitelist(allow_guest=True)
def africas_talking_delivery_report(**kwargs) -> dict[str, Any]:
	"""
	Receive Africa's Talking SMS delivery reports.

	Recommended callback URL:
	/api/method/rentals.sms.callbacks.africas_talking_delivery_report?secret=YOUR_SECRET
	"""
	try:
		payload = _get_request_payload()
		payload.update({key: value for key, value in kwargs.items() if value not in (None, "")})

		_validate_callback_secret(payload)

		message_id = _first_present(payload, "messageId", "message_id", "id", "MessageId", "messageID")
		phone_number = _first_present(payload, "phoneNumber", "phone_number", "number", "to", "recipient")
		provider_status = _first_present(payload, "status", "deliveryStatus", "delivery_status")
		cost = _first_present(payload, "cost", "price")
		network_code = _first_present(payload, "networkCode", "network_code")
		failure_reason = _first_present(payload, "failureReason", "failure_reason", "errorMessage", "error")

		status = _normalize_callback_status(provider_status)
		normalized_phone = _normalize_callback_phone(phone_number)
		log_name = _find_sms_log(message_id, normalized_phone)

		if not log_name:
			frappe.log_error(_json_dumps(payload), "Rentals SMS Delivery Report Log Not Found")
			return {
				"ok": False,
				"message": "SMS log not found for delivery report.",
				"message_id": message_id,
				"phone_number": normalized_phone or phone_number,
			}

		log = _update_sms_log_from_callback(
			log_name=log_name,
			payload=payload,
			message_id=message_id,
			status=status,
			normalized_phone=normalized_phone,
			provider_status=provider_status,
			cost=cost,
			network_code=network_code,
			failure_reason=failure_reason,
		)

		campaign_recipient = _update_campaign_recipient_from_log(log, status, failure_reason)
		frappe.db.commit()

		return {
			"ok": True,
			"message": "Delivery report processed.",
			"sms_log": log_name,
			"campaign_recipient": campaign_recipient,
			"status": status,
		}

	except frappe.PermissionError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Delivery Report Error")
		return {"ok": False, "message": "Failed to process delivery report."}
