"""
SMS template helpers for Rentals.

Templates use Frappe/Jinja rendering syntax, for example:
- {{ tenant_name }}
- {{ lease_name }}
- {{ amount }}
- {{ due_date }}
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _

from rentals.sms.utils import SMSValidationError, normalize_sms_message

SMS_TEMPLATE_DOCTYPE = "Rentals SMS Template"


def _require_sms_template_permission():
	if not (frappe.has_role("System Manager") or frappe.has_role("Agent")):
		frappe.throw(_("You are not permitted to manage SMS templates."), frappe.PermissionError)


def _json_loads(value: Any) -> dict[str, Any]:
	if isinstance(value, dict):
		return value
	if not value:
		return {}
	try:
		parsed = json.loads(value)
		return parsed if isinstance(parsed, dict) else {}
	except Exception:
		return {}


def render_template_message(template_text: str, context: dict[str, Any] | None = None) -> str:
	"""Render raw template text using a context dict and validate SMS length."""
	context = context or {}
	try:
		rendered = frappe.render_template(template_text or "", context)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Template Render Error")
		raise

	return normalize_sms_message(rendered)


def get_sms_template(template_name: str | None = None, template_type: str | None = None):
	"""Return an active template by name or the default active template for a type."""
	try:
		if not frappe.db.exists("DocType", SMS_TEMPLATE_DOCTYPE):
			return None
		if template_name:
			template = frappe.get_doc(SMS_TEMPLATE_DOCTYPE, template_name)
			return template if template.status == "Active" else None
		if template_type:
			name = frappe.db.get_value(
				SMS_TEMPLATE_DOCTYPE,
				{"template_type": template_type, "status": "Active", "is_default": 1},
				"name",
			)
			return frappe.get_doc(SMS_TEMPLATE_DOCTYPE, name) if name else None
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Template Lookup Error")
	return None


def render_sms_template(
	*,
	template_name: str | None = None,
	template_type: str | None = None,
	context: dict[str, Any] | None = None,
	fallback_message: str | None = None,
) -> tuple[str, str | None]:
	"""
	Render a configured/default template; fall back to fallback_message.

	Returns (message, template_name_used).
	"""
	template = get_sms_template(template_name=template_name, template_type=template_type)
	if template:
		return render_template_message(template.message, context or {}), template.name

	if fallback_message:
		return normalize_sms_message(fallback_message), None

	raise SMSValidationError(_("SMS template or fallback message is required."))


@frappe.whitelist()
def preview_sms_template(template_name: str | None = None, context: str | dict[str, Any] | None = None) -> dict[str, Any]:
	"""Render a template preview from its sample context or supplied context."""
	_require_sms_template_permission()

	if not template_name:
		frappe.throw(_("Template name is required."))

	template = frappe.get_doc(SMS_TEMPLATE_DOCTYPE, template_name)
	preview_context = _json_loads(context) if context else _json_loads(template.sample_context)
	message = render_template_message(template.message, preview_context)

	return {
		"ok": True,
		"template": template.name,
		"message": message,
		"length": len(message),
	}


@frappe.whitelist()
def get_sms_template_message(template_name: str | None = None) -> dict[str, Any]:
	"""Return raw template message for Desk helpers like SMS Campaign."""
	_require_sms_template_permission()

	if not template_name:
		frappe.throw(_("Template name is required."))

	template = frappe.get_doc(SMS_TEMPLATE_DOCTYPE, template_name)
	if template.status != "Active":
		frappe.throw(_("Only active SMS templates can be used."))

	return {
		"ok": True,
		"template": template.name,
		"template_type": template.template_type,
		"message": template.message,
	}
