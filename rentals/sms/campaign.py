"""
Bulk SMS campaign helpers for Rentals.

Handles:
- resolving campaign recipients from tenants/leases/invoices/manual numbers
- tenant SMS opt-out filtering
- queueing campaign sends
- chunked campaign processing
- recipient and campaign status counters
"""

from __future__ import annotations

import re
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from rentals.sms.africas_talking import send_sms
from rentals.sms.preferences import can_send_sms_to_recipient
from rentals.sms.templates import render_template_message
from rentals.sms.utils import SMSValidationError, get_default_country_code, normalize_phone_number

SMS_CAMPAIGN_DOCTYPE = "Rentals SMS Campaign"
SMS_CAMPAIGN_RECIPIENT_DOCTYPE = "Rentals SMS Campaign Recipient"
SMS_CAMPAIGN_QUEUE = "long"
SMS_CAMPAIGN_CHUNK_SIZE = 100

SENT_STATUSES = {"Submitted", "Success", "Sent", "Buffered", "Delivered"}
FAILED_STATUSES = {"Failed", "Rejected", "InsufficientBalance", "UserInBlacklist", "Expired"}
SKIPPED_STATUSES = {"InvalidPhoneNumber", "NotSent", "OptedOut"}
FINAL_STATUSES = SENT_STATUSES | FAILED_STATUSES | SKIPPED_STATUSES


def _has_sms_campaign_permission() -> bool:
	"""Allow System Managers and Agents to operate campaigns."""
	return bool(frappe.has_role("System Manager") or frappe.has_role("Agent"))


def _require_sms_campaign_permission():
	if not _has_sms_campaign_permission():
		frappe.throw(_("You are not permitted to manage SMS campaigns."), frappe.PermissionError)


def _first_present(*values: Any) -> Any | None:
	for value in values:
		if value not in (None, ""):
			return value
	return None


def _split_manual_numbers(value: str | None) -> list[str]:
	"""Split numbers separated by new lines, commas, semicolons, or pipes."""
	if not value:
		return []
	return [item.strip() for item in re.split(r"[\n,;|]+", value) if item.strip()]


def _get_tenant_phone(tenant: str | None, fallback_phone: str | None = None) -> str | None:
	"""Return the best phone number from a Tenant record and optional fallback."""
	if not tenant:
		return fallback_phone

	row = frappe.db.get_value("Tenant", tenant, ["phone_number", "mobile_no"], as_dict=True)
	if not row:
		return fallback_phone

	return _first_present(fallback_phone, row.get("phone_number"), row.get("mobile_no"))


def _get_tenant_name(tenant: str | None, fallback_name: str | None = None) -> str | None:
	if not tenant:
		return fallback_name
	return _first_present(fallback_name, frappe.db.get_value("Tenant", tenant, "full_name"), tenant)


def _should_exclude_opted_out(campaign=None) -> bool:
	if not campaign:
		return True
	value = getattr(campaign, "exclude_opted_out_recipients", None)
	return bool(1 if value in (None, "") else int(value or 0))


def _append_recipient(
	*,
	recipients: list[dict[str, Any]],
	seen_phones: set[str],
	phone_number: str | None,
	tenant: str | None = None,
	tenant_name: str | None = None,
	lease_agreement: str | None = None,
	property_name: str | None = None,
	default_country_code: str | None = None,
	exclude_opted_out: bool = True,
):
	"""Normalize, deduplicate, and append a campaign recipient row."""
	if not phone_number:
		return

	default_country_code = default_country_code or get_default_country_code()

	try:
		normalized_phone = normalize_phone_number(
			phone_number,
			default_country_code=default_country_code,
		)
	except SMSValidationError as exc:
		recipients.append({
			"tenant": tenant,
			"tenant_name": tenant_name,
			"lease_agreement": lease_agreement,
			"property": property_name,
			"phone_number": phone_number,
			"normalized_phone": None,
			"status": "InvalidPhoneNumber",
			"error": str(exc),
		})
		return

	if normalized_phone in seen_phones:
		return

	seen_phones.add(normalized_phone)
	row = {
		"tenant": tenant,
		"tenant_name": tenant_name,
		"lease_agreement": lease_agreement,
		"property": property_name,
		"phone_number": phone_number,
		"normalized_phone": normalized_phone,
		"status": "Queued",
		"error": None,
	}

	if exclude_opted_out and tenant:
		allowed, reason = can_send_sms_to_recipient(
			recipient_doctype="Tenant",
			recipient_name=tenant,
			sms_category="Campaign",
		)
		if not allowed:
			row["status"] = "OptedOut"
			row["error"] = reason or _("Recipient has opted out of campaign SMS.")

	recipients.append(row)


def _get_active_tenant_recipients(default_country_code: str, *, campaign=None) -> list[dict[str, Any]]:
	recipients: list[dict[str, Any]] = []
	seen_phones: set[str] = set()

	tenants = frappe.get_all(
		"Tenant",
		filters={"status": "Active"},
		fields=["name", "full_name", "phone_number", "mobile_no"],
		order_by="full_name asc",
	)

	for tenant in tenants:
		phone_number = _first_present(tenant.get("phone_number"), tenant.get("mobile_no"))
		_append_recipient(
			recipients=recipients,
			seen_phones=seen_phones,
			phone_number=phone_number,
			tenant=tenant.get("name"),
			tenant_name=tenant.get("full_name"),
			default_country_code=default_country_code,
			exclude_opted_out=_should_exclude_opted_out(campaign),
		)

	return recipients


def _get_lease_recipients(
	*,
	default_country_code: str,
	property_name: str | None = None,
	landlord: str | None = None,
	lease_status: str | None = "Active",
	campaign=None,
) -> list[dict[str, Any]]:
	recipients: list[dict[str, Any]] = []
	seen_phones: set[str] = set()
	filters: dict[str, Any] = {}

	if property_name:
		filters["property"] = property_name
	if landlord:
		filters["landlord"] = landlord
	if lease_status:
		filters["status"] = lease_status

	leases = frappe.get_all(
		"Lease Agreement",
		filters=filters,
		fields=["name", "tenant", "tenant_name", "tenant_phone_number", "property"],
		order_by="tenant_name asc",
	)

	for lease in leases:
		tenant = lease.get("tenant")
		phone_number = _get_tenant_phone(tenant, lease.get("tenant_phone_number"))
		tenant_name = _get_tenant_name(tenant, lease.get("tenant_name"))

		_append_recipient(
			recipients=recipients,
			seen_phones=seen_phones,
			phone_number=phone_number,
			tenant=tenant,
			tenant_name=tenant_name,
			lease_agreement=lease.get("name"),
			property_name=lease.get("property"),
			default_country_code=default_country_code,
			exclude_opted_out=_should_exclude_opted_out(campaign),
		)

	return recipients


def _get_outstanding_invoice_recipients(default_country_code: str, *, campaign=None) -> list[dict[str, Any]]:
	"""Return tenants linked to unpaid Sales Invoices for leases."""
	recipients: list[dict[str, Any]] = []
	seen_phones: set[str] = set()
	seen_leases: set[str] = set()

	invoice_rows = frappe.db.sql(
		"""
		select
			si.name,
			si.custom_lease_agreement,
			si.outstanding_amount,
			si.due_date
		from `tabSales Invoice` si
		where si.docstatus = 1
		  and si.outstanding_amount > 0
		  and ifnull(si.custom_lease_agreement, '') != ''
		order by si.due_date asc, si.name asc
		""",
		as_dict=True,
	)

	for invoice in invoice_rows:
		lease_name = invoice.get("custom_lease_agreement")
		if not lease_name or lease_name in seen_leases:
			continue
		seen_leases.add(lease_name)

		try:
			lease = frappe.db.get_value(
				"Lease Agreement",
				lease_name,
				["name", "tenant", "tenant_name", "tenant_phone_number", "property"],
				as_dict=True,
			)
		except Exception:
			lease = None

		if not lease:
			continue

		tenant = lease.get("tenant")
		phone_number = _get_tenant_phone(tenant, lease.get("tenant_phone_number"))
		tenant_name = _get_tenant_name(tenant, lease.get("tenant_name"))

		_append_recipient(
			recipients=recipients,
			seen_phones=seen_phones,
			phone_number=phone_number,
			tenant=tenant,
			tenant_name=tenant_name,
			lease_agreement=lease.get("name"),
			property_name=lease.get("property"),
			default_country_code=default_country_code,
			exclude_opted_out=_should_exclude_opted_out(campaign),
		)

	return recipients


def _get_manual_recipients(campaign, default_country_code: str) -> list[dict[str, Any]]:
	recipients: list[dict[str, Any]] = []
	seen_phones: set[str] = set()

	for phone_number in _split_manual_numbers(campaign.manual_numbers):
		_append_recipient(
			recipients=recipients,
			seen_phones=seen_phones,
			phone_number=phone_number,
			default_country_code=default_country_code,
			exclude_opted_out=False,
		)

	return recipients


def resolve_campaign_recipients(campaign) -> list[dict[str, Any]]:
	"""Resolve recipients for a campaign target type."""
	default_country_code = get_default_country_code()
	target_type = campaign.target_type

	if target_type == "All Active Tenants":
		return _get_active_tenant_recipients(default_country_code, campaign=campaign)

	if target_type == "Tenants by Property":
		if not campaign.property:
			frappe.throw(_("Property is required for Tenants by Property campaigns."))
		return _get_lease_recipients(
			default_country_code=default_country_code,
			property_name=campaign.property,
			lease_status=campaign.lease_status or "Active",
			campaign=campaign,
		)

	if target_type == "Tenants by Landlord":
		if not campaign.landlord:
			frappe.throw(_("Landlord is required for Tenants by Landlord campaigns."))
		return _get_lease_recipients(
			default_country_code=default_country_code,
			landlord=campaign.landlord,
			lease_status=campaign.lease_status or "Active",
			campaign=campaign,
		)

	if target_type == "Tenants with Active Leases":
		return _get_lease_recipients(
			default_country_code=default_country_code,
			lease_status=campaign.lease_status or "Active",
			campaign=campaign,
		)

	if target_type == "Tenants with Outstanding Invoices":
		return _get_outstanding_invoice_recipients(default_country_code, campaign=campaign)

	if target_type == "Manual Numbers":
		if not campaign.manual_numbers:
			frappe.throw(_("Manual Numbers is required for Manual Numbers campaigns."))
		return _get_manual_recipients(campaign, default_country_code)

	frappe.throw(_("Unsupported SMS campaign target type: {0}").format(target_type))


def _compute_totals(campaign) -> dict[str, int]:
	valid_statuses = {"Queued", "Sending"} | SENT_STATUSES
	total_recipients = 0
	total_sent = 0
	total_failed = 0
	total_skipped = 0

	for row in campaign.recipients or []:
		status = row.status or "Queued"
		if status in valid_statuses:
			total_recipients += 1
		if status in SENT_STATUSES:
			total_sent += 1
		if status in FAILED_STATUSES:
			total_failed += 1
		if status in SKIPPED_STATUSES:
			total_skipped += 1

	return {
		"total_recipients": total_recipients,
		"total_sent": total_sent,
		"total_failed": total_failed,
		"total_skipped": total_skipped,
	}


def update_campaign_totals(campaign_name: str) -> dict[str, int]:
	"""Recalculate and persist summary counters for a campaign."""
	campaign = frappe.get_doc(SMS_CAMPAIGN_DOCTYPE, campaign_name)
	totals = _compute_totals(campaign)

	remaining = sum(1 for row in campaign.recipients or [] if row.status in {"Queued", "Sending"})
	failed = totals["total_failed"]
	sent = totals["total_sent"]
	skipped = totals["total_skipped"]

	status = campaign.status
	if campaign.status not in {"Cancelled"}:
		if remaining:
			status = campaign.status if campaign.status in {"Queued", "Sending"} else "Draft"
		elif sent:
			status = "Completed"
		elif failed:
			status = "Failed"
		elif skipped:
			status = "Completed"
		else:
			status = "Draft"

	frappe.db.set_value(
		SMS_CAMPAIGN_DOCTYPE,
		campaign_name,
		{
			"total_recipients": totals["total_recipients"],
			"total_sent": totals["total_sent"],
			"total_failed": totals["total_failed"],
			"total_skipped": totals["total_skipped"],
			"status": status,
		},
		update_modified=True,
	)
	return totals


@frappe.whitelist()
def build_campaign_recipients(campaign_name: str) -> dict[str, Any]:
	"""Build and save recipients for a campaign."""
	_require_sms_campaign_permission()

	campaign = frappe.get_doc(SMS_CAMPAIGN_DOCTYPE, campaign_name)
	if campaign.status in {"Queued", "Sending"}:
		frappe.throw(_("Cannot rebuild recipients while the campaign is queued or sending."))
	if campaign.status == "Cancelled":
		frappe.throw(_("Cannot rebuild a cancelled campaign."))

	recipients = resolve_campaign_recipients(campaign)
	campaign.set("recipients", [])

	for row in recipients:
		campaign.append("recipients", row)

	totals = _compute_totals(campaign)
	campaign.total_recipients = totals["total_recipients"]
	campaign.total_sent = totals["total_sent"]
	campaign.total_failed = totals["total_failed"]
	campaign.total_skipped = totals["total_skipped"]
	campaign.status = "Draft"
	campaign.last_error = None
	campaign.save(ignore_permissions=True)

	return {
		"ok": True,
		"message": _("Campaign recipients built."),
		"campaign": campaign.name,
		"total_recipients": campaign.total_recipients,
		"total_failed": campaign.total_failed,
		"total_skipped": campaign.total_skipped,
	}


@frappe.whitelist()
def enqueue_campaign_send(campaign_name: str) -> dict[str, Any]:
	"""Queue a campaign send job."""
	_require_sms_campaign_permission()

	campaign = frappe.get_doc(SMS_CAMPAIGN_DOCTYPE, campaign_name)
	if campaign.status in {"Queued", "Sending"}:
		frappe.throw(_("Campaign is already queued or sending."))
	if campaign.status == "Cancelled":
		frappe.throw(_("Cannot send a cancelled campaign."))

	queued_count = sum(1 for row in campaign.recipients or [] if row.status == "Queued" and row.normalized_phone)
	if not queued_count:
		# Build automatically if the user forgot to press Build Recipients.
		build_campaign_recipients(campaign_name)
		campaign.reload()
		queued_count = sum(1 for row in campaign.recipients or [] if row.status == "Queued" and row.normalized_phone)

	if not queued_count:
		frappe.throw(_("No valid queued recipients were found for this campaign."))

	frappe.db.set_value(
		SMS_CAMPAIGN_DOCTYPE,
		campaign_name,
		{"status": "Queued", "last_error": None},
		update_modified=True,
	)

	frappe.enqueue(
		"rentals.sms.campaign.send_campaign",
		queue=SMS_CAMPAIGN_QUEUE,
		enqueue_after_commit=True,
		campaign_name=campaign_name,
	)

	return {
		"ok": True,
		"message": _("Campaign queued for sending."),
		"campaign": campaign_name,
		"queued_recipients": queued_count,
	}


def _mark_recipient(row_name: str, values: dict[str, Any]):
	try:
		frappe.db.set_value(
			SMS_CAMPAIGN_RECIPIENT_DOCTYPE,
			row_name,
			values,
			update_modified=True,
		)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Campaign Recipient Update Error")


def _campaign_message_context(campaign, row) -> dict[str, Any]:
	return {
		"campaign": campaign.name,
		"campaign_title": campaign.campaign_title,
		"target_type": campaign.target_type,
		"tenant": getattr(row, "tenant", None),
		"tenant_name": _first_present(getattr(row, "tenant_name", None), getattr(row, "tenant", None), "Tenant"),
		"lease_name": getattr(row, "lease_agreement", None),
		"lease_agreement": getattr(row, "lease_agreement", None),
		"property": getattr(row, "property", None),
		"property_label": getattr(row, "property", None),
		"phone_number": getattr(row, "normalized_phone", None) or getattr(row, "phone_number", None),
	}


def _render_campaign_message(campaign, row) -> str:
	return render_template_message(campaign.message, _campaign_message_context(campaign, row))


def _send_one_campaign_recipient(campaign, row) -> None:
	"""Send one campaign recipient so templates and opt-out checks remain per-recipient."""
	_mark_recipient(row.name, {"status": "Sending", "error": None})

	try:
		message = _render_campaign_message(campaign, row)
		result = send_sms(
			recipients=row.normalized_phone,
			message=message,
			recipient_doctype="Tenant" if row.tenant else None,
			recipient_name=row.tenant,
			reference_doctype=SMS_CAMPAIGN_DOCTYPE,
			reference_name=campaign.name,
			sms_campaign=campaign.name,
			sms_category="Campaign",
			sms_template=campaign.sms_template,
			enqueue=True,
		)
	except Exception as exc:
		_mark_recipient(row.name, {"status": "Failed", "error": str(exc)})
		return

	provider_result = (result.get("recipients") or [{}])[0]
	status = provider_result.get("status") or ("OptedOut" if result.get("skipped") else "Submitted")
	_mark_recipient(row.name, {
		"status": status,
		"sms_log": provider_result.get("log_name"),
		"error": provider_result.get("error"),
	})


def _send_recipient_chunk(campaign, rows) -> None:
	"""Send one chunk and update its child recipient rows."""
	for row in rows:
		_send_one_campaign_recipient(campaign, row)


def send_campaign(campaign_name: str) -> dict[str, Any]:
	"""Worker function that sends a campaign in chunks."""
	campaign = frappe.get_doc(SMS_CAMPAIGN_DOCTYPE, campaign_name)
	if campaign.status == "Cancelled":
		return {"ok": False, "skipped": True, "reason": "Campaign cancelled."}

	frappe.db.set_value(
		SMS_CAMPAIGN_DOCTYPE,
		campaign_name,
		{"status": "Sending", "last_error": None},
		update_modified=True,
	)

	try:
		campaign.reload()
		rows = [row for row in campaign.recipients or [] if row.status == "Queued" and row.normalized_phone]

		for start in range(0, len(rows), SMS_CAMPAIGN_CHUNK_SIZE):
			chunk = rows[start:start + SMS_CAMPAIGN_CHUNK_SIZE]
			_send_recipient_chunk(campaign, chunk)
			frappe.db.commit()

		frappe.db.set_value(SMS_CAMPAIGN_DOCTYPE, campaign_name, "sent_on", now_datetime(), update_modified=True)
		totals = update_campaign_totals(campaign_name)
		return {"ok": True, "campaign": campaign_name, **totals}

	except Exception as exc:
		error = str(exc)
		frappe.db.set_value(
			SMS_CAMPAIGN_DOCTYPE,
			campaign_name,
			{"status": "Failed", "last_error": error},
			update_modified=True,
		)
		frappe.log_error(frappe.get_traceback(), "Rentals SMS Campaign Send Error")
		return {"ok": False, "campaign": campaign_name, "error": error}
