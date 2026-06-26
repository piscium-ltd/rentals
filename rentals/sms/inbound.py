"""
Africa's Talking inbound SMS handling for Rentals.

Handles incoming keyword messages like STOP, START, and HELP so tenants or
landlords can control their SMS preference from their phone.
"""

from __future__ import annotations

import hmac
import json
import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from rentals.sms.africas_talking import SMS_SETTINGS_DOCTYPE, send_sms
from rentals.sms.preferences import (
	find_sms_recipients_by_phone,
	set_sms_preference_for_recipient,
)
from rentals.sms.utils import SMSValidationError, get_default_country_code, normalize_phone_number

SMS_INBOUND_LOG_DOCTYPE = "Rentals SMS Inbound Log"

DEFAULT_STOP_KEYWORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}
DEFAULT_START_KEYWORDS = {"START", "YES", "RESUME", "SUBSCRIBE", "UNSTOP"}
DEFAULT_HELP_KEYWORDS = {"HELP", "INFO"}


def _json_dumps(value: Any) -> str:
	try:
		return json.dumps(value, default=str, ensure_ascii=False)
	except Exception:
		return str(value)


def _split_keywords(value: str | None, defaults: set[str]) -> set[str]:
	if not value:
		return set(defaults)
	keywords = {item.strip().upper() for item in re.split(r"[,\n;|]+", value) if item.strip()}
	return keywords or set(defaults)


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


def _get_sms_settings():
	try:
		if frappe.db.exists("DocType", SMS_SETTINGS_DOCTYPE):
			return frappe.get_single(SMS_SETTINGS_DOCTYPE)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Inbound Settings Error")
	return None


def _get_inbound_callback_secret(settings=None) -> str | None:
	settings = settings or _get_sms_settings()
	if not settings:
		return None
	try:
		secret = settings.get_password("inbound_callback_secret") if hasattr(settings, "get_password") else settings.inbound_callback_secret
		return secret or None
	except Exception:
		return None


def _validate_inbound_secret(payload: dict[str, Any], settings=None) -> None:
	"""
	Validate optional inbound callback secret.

	When blank in Rentals SMS Settings, callbacks are accepted. Once configured,
	pass it as ?secret=..., ?key=..., or in X-Rentals-SMS-Inbound-Secret /
	X-AT-Callback-Secret header.
	"""
	configured_secret = _get_inbound_callback_secret(settings=settings)
	if not configured_secret:
		return

	provided_secret = (
		_first_present(payload, "secret", "key", "callback_secret", "inbound_callback_secret")
		or _header_value("X-Rentals-SMS-Inbound-Secret", "X-AT-Callback-Secret")
	)

	if not provided_secret or not hmac.compare_digest(str(provided_secret), str(configured_secret)):
		frappe.throw(_("Invalid SMS inbound callback secret."), frappe.PermissionError)


def _normalize_inbound_phone(phone_number: str | None) -> str | None:
	if not phone_number:
		return None
	try:
		return normalize_phone_number(phone_number, default_country_code=get_default_country_code())
	except SMSValidationError:
		return str(phone_number).strip() or None


def _canonical_message_text(message: str | None) -> str:
	return " ".join(str(message or "").strip().split())


def _extract_keyword(message: str | None) -> str | None:
	text = _canonical_message_text(message)
	if not text:
		return None
	# Match exact keyword or first token. This supports messages like "STOP please".
	first_token = re.split(r"\s+", text, maxsplit=1)[0]
	return re.sub(r"[^A-Za-z0-9_]", "", first_token).upper() or None


def _classify_keyword(keyword: str | None, settings=None) -> str:
	if not keyword:
		return "Unknown"

	settings = settings or _get_sms_settings()
	stop_keywords = _split_keywords(getattr(settings, "stop_keywords", None), DEFAULT_STOP_KEYWORDS) if settings else DEFAULT_STOP_KEYWORDS
	start_keywords = _split_keywords(getattr(settings, "start_keywords", None), DEFAULT_START_KEYWORDS) if settings else DEFAULT_START_KEYWORDS
	help_keywords = _split_keywords(getattr(settings, "help_keywords", None), DEFAULT_HELP_KEYWORDS) if settings else DEFAULT_HELP_KEYWORDS

	keyword = keyword.upper()
	if keyword in stop_keywords:
		return "OptOut"
	if keyword in start_keywords:
		return "OptIn"
	if keyword in help_keywords:
		return "Help"
	return "Unknown"


def _log_inbound_message(
	*,
	payload: dict[str, Any],
	from_phone: str | None,
	normalized_phone: str | None,
	to_phone: str | None,
	message: str | None,
	keyword: str | None,
	action: str,
	status: str,
	matches: list[dict[str, Any]],
	provider_message_id: str | None,
	link_id: str | None,
	network_code: str | None,
	error: str | None = None,
) -> str | None:
	try:
		first_match = matches[0] if matches else {}
		log = frappe.get_doc({
			"doctype": SMS_INBOUND_LOG_DOCTYPE,
			"from_phone": from_phone or normalized_phone,
			"normalized_phone": normalized_phone,
			"to_phone": to_phone,
			"message": message,
			"keyword": keyword,
			"action": action,
			"status": status,
			"received_on": now_datetime(),
			"recipient_doctype": first_match.get("doctype"),
			"recipient_name": first_match.get("name"),
			"matched_recipient_count": len(matches),
			"matched_recipients": _json_dumps(matches),
			"provider_message_id": provider_message_id,
			"link_id": link_id,
			"network_code": network_code,
			"raw_payload": _json_dumps(payload),
			"error": error,
		})
		log.insert(ignore_permissions=True)
		return log.name
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Inbound Log Creation Error")
		return None


def _apply_keyword_action(action: str, matches: list[dict[str, Any]], keyword: str | None) -> tuple[str, str | None]:
	"""Apply opt-in/out keyword to matched Tenant/Landlord records."""
	if action == "Unknown":
		return "Ignored", "Inbound SMS keyword was not recognized."

	if action == "Help":
		return "Processed", None

	if not matches:
		return "Ignored", "No Tenant or Landlord record matched the sender phone number."

	allow_sms = action == "OptIn"
	reason = None if allow_sms else _("Inbound SMS keyword: {0}").format(keyword or action)
	for match in matches:
		set_sms_preference_for_recipient(
			recipient_doctype=match.get("doctype"),
			recipient_name=match.get("name"),
			allow_sms=allow_sms,
			reason=reason,
		)

	return "Processed", None


def _auto_reply_message(action: str, settings=None) -> str | None:
	settings = settings or _get_sms_settings()
	if not settings or not int(getattr(settings, "auto_reply_to_inbound_keywords", 0) or 0):
		return None

	if action == "OptOut":
		return getattr(settings, "opt_out_auto_reply", None)
	if action == "OptIn":
		return getattr(settings, "opt_in_auto_reply", None)
	if action == "Help":
		return getattr(settings, "help_auto_reply", None)
	return None


def _send_keyword_auto_reply(
	*,
	to_phone: str | None,
	message: str | None,
	action: str,
	inbound_log: str | None,
	matches: list[dict[str, Any]],
) -> dict[str, Any] | None:
	if not to_phone or not message:
		return None

	first_match = matches[0] if matches else {}
	try:
		return send_sms(
			recipients=to_phone,
			message=message,
			recipient_doctype=first_match.get("doctype"),
			recipient_name=first_match.get("name"),
			reference_doctype=SMS_INBOUND_LOG_DOCTYPE,
			reference_name=inbound_log,
			sms_category="Callback",
			enqueue=True,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Inbound Auto Reply Error")
		return None


@frappe.whitelist(allow_guest=True)
def africas_talking_inbound_sms(**kwargs) -> dict[str, Any]:
	"""
	Receive Africa's Talking inbound SMS callbacks.

	Recommended callback URL:
	/api/method/rentals.sms.inbound.africas_talking_inbound_sms?secret=YOUR_SECRET
	"""
	try:
		payload = _get_request_payload()
		payload.update({key: value for key, value in kwargs.items() if value not in (None, "")})

		settings = _get_sms_settings()
		_validate_inbound_secret(payload, settings=settings)

		from_phone = _first_present(payload, "from", "fromPhone", "from_phone", "phoneNumber", "phone_number", "msisdn", "MSISDN")
		to_phone = _first_present(payload, "to", "toPhone", "to_phone", "shortCode", "short_code", "receiver")
		message = _first_present(payload, "text", "message", "messageText", "body", "content")
		provider_message_id = _first_present(payload, "id", "messageId", "message_id", "MessageId")
		link_id = _first_present(payload, "linkId", "link_id")
		network_code = _first_present(payload, "networkCode", "network_code")

		normalized_phone = _normalize_inbound_phone(from_phone)
		keyword = _extract_keyword(message)
		action = _classify_keyword(keyword, settings=settings)

		processing_enabled = bool(int(getattr(settings, "enable_inbound_keyword_processing", 1) if settings else 1))
		matches = find_sms_recipients_by_phone(normalized_phone or from_phone) if normalized_phone or from_phone else []

		if not processing_enabled:
			status = "Ignored"
			error = "Inbound keyword processing is disabled."
		elif not from_phone or not message:
			status = "Failed"
			error = "Inbound SMS callback is missing sender phone or message text."
		else:
			status, error = _apply_keyword_action(action, matches, keyword)

		inbound_log = _log_inbound_message(
			payload=payload,
			from_phone=from_phone,
			normalized_phone=normalized_phone,
			to_phone=to_phone,
			message=message,
			keyword=keyword,
			action=action if processing_enabled else "Ignored",
			status=status,
			matches=matches,
			provider_message_id=provider_message_id,
			link_id=link_id,
			network_code=network_code,
			error=error,
		)

		auto_reply_result = None
		if status == "Processed" and action in {"OptOut", "OptIn", "Help"}:
			auto_reply_result = _send_keyword_auto_reply(
				to_phone=normalized_phone or from_phone,
				message=_auto_reply_message(action, settings=settings),
				action=action,
				inbound_log=inbound_log,
				matches=matches,
			)

		frappe.db.commit()
		return {
			"ok": status != "Failed",
			"message": "Inbound SMS processed." if status == "Processed" else "Inbound SMS logged.",
			"status": status,
			"action": action if processing_enabled else "Ignored",
			"keyword": keyword,
			"inbound_log": inbound_log,
			"matched_recipients": len(matches),
			"auto_reply_sent": bool(auto_reply_result and auto_reply_result.get("ok")),
		}

	except frappe.PermissionError:
		raise
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Inbound Callback Error")
		return {"ok": False, "message": "Failed to process inbound SMS."}
