# Copyright (c) 2026, Piscium Solutions LTD and contributors
# For license information, please see license.txt

"""SMS cleanup, retention, and operational safety helpers.

This module keeps the SMS subsystem fast in production without deleting
important audit records by default. Scheduled cleanup archives old records.
Manual System Manager endpoints can preview or run cleanup with the same rules.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, now, nowdate

FAILED_STATUSES = (
	"Failed",
	"Rejected",
	"InvalidPhoneNumber",
	"InsufficientBalance",
	"UserInBlacklist",
	"Expired",
	"Unknown",
)

DEFAULT_SMS_RETENTION_DAYS = 365
DEFAULT_INBOUND_RETENTION_DAYS = 365
DEFAULT_DELETE_ARCHIVED_AFTER_DAYS = 730
DEFAULT_BATCH_SIZE = 1000


@frappe.whitelist()
def preview_sms_cleanup():
	"""Preview cleanup impact using the current Rentals SMS Settings."""
	frappe.only_for("System Manager")
	return get_cleanup_preview()


@frappe.whitelist()
def run_sms_cleanup(dry_run=1, force_delete=0):
	"""Run SMS cleanup manually.

	Args:
		dry_run: when true, only returns counts.
		force_delete: when true, deletes eligible records instead of archiving them.
	"""
	frappe.only_for("System Manager")
	return cleanup_sms_records(dry_run=cint(dry_run), force_delete=cint(force_delete), triggered_by="Manual")


def run_scheduled_sms_cleanup():
	"""Scheduled cleanup entry point. Runs only when enabled in settings."""
	settings = _get_settings()
	if not settings or not cint(settings.get("enable_sms_cleanup")):
		return {"ok": True, "message": "SMS cleanup is disabled."}

	return cleanup_sms_records(dry_run=0, force_delete=0, triggered_by="Scheduler")


def get_cleanup_preview(settings=None):
	settings = settings or _get_settings()
	if not settings:
		return {"ok": False, "message": "Rentals SMS Settings not found."}

	cleanup_mode = _get_cleanup_mode(settings=settings, force_delete=0)
	return {
		"ok": True,
		"message": "SMS cleanup preview generated.",
		"enabled": bool(cint(settings.get("enable_sms_cleanup"))),
		"cleanup_mode": cleanup_mode,
		"sms_log": _preview_for_doctype("Rentals SMS Log", settings=settings, cleanup_mode=cleanup_mode),
		"inbound_log": _preview_for_doctype("Rentals SMS Inbound Log", settings=settings, cleanup_mode=cleanup_mode),
	}


def cleanup_sms_records(dry_run=1, force_delete=0, triggered_by="Manual"):
	settings = _get_settings()
	if not settings:
		return {"ok": False, "message": "Rentals SMS Settings not found."}

	if triggered_by != "Manual" and not cint(settings.get("enable_sms_cleanup")):
		return {"ok": True, "message": "SMS cleanup is disabled."}

	cleanup_mode = _get_cleanup_mode(settings=settings, force_delete=force_delete)
	preview = get_cleanup_preview(settings=settings)
	if dry_run:
		preview["dry_run"] = True
		preview["message"] = "SMS cleanup dry run completed. No records were changed."
		return preview

	result = {
		"ok": True,
		"message": "SMS cleanup completed.",
		"triggered_by": triggered_by,
		"cleanup_mode": cleanup_mode,
		"sms_log": _cleanup_doctype("Rentals SMS Log", settings=settings, cleanup_mode=cleanup_mode),
		"inbound_log": _cleanup_doctype("Rentals SMS Inbound Log", settings=settings, cleanup_mode=cleanup_mode),
	}

	frappe.db.commit()
	return result


def _get_settings():
	try:
		return frappe.get_cached_doc("Rentals SMS Settings")
	except Exception:
		return None


def _get_cleanup_mode(*, settings, force_delete: int) -> str:
	if cint(force_delete):
		return "Delete"
	if cint(settings.get("archive_instead_of_delete")):
		return "Archive"
	return "Delete"


def _preview_for_doctype(doctype: str, *, settings, cleanup_mode: str) -> dict:
	filters, params = _get_filters(doctype, settings=settings, cleanup_mode=cleanup_mode)
	count = frappe.db.sql(
		f"select count(*) from `tab{doctype}` where {' and '.join(filters)}",
		params,
	)[0][0]

	oldest = frappe.db.sql(
		f"select min(creation) from `tab{doctype}` where {' and '.join(filters)}",
		params,
	)[0][0]

	return {
		"doctype": doctype,
		"eligible_records": cint(count),
		"oldest_eligible_record": oldest,
		"retention_days": _retention_days_for_doctype(doctype, settings=settings, cleanup_mode=cleanup_mode),
		"batch_size": _batch_size(settings),
	}


def _cleanup_doctype(doctype: str, *, settings, cleanup_mode: str) -> dict:
	filters, params = _get_filters(doctype, settings=settings, cleanup_mode=cleanup_mode)
	params["limit"] = _batch_size(settings)

	names = frappe.db.sql(
		f"""
		select name
		from `tab{doctype}`
		where {' and '.join(filters)}
		order by creation asc
		limit %(limit)s
		""",
		params,
		as_dict=True,
	)
	names = [row.name for row in names]

	if not names:
		return {"doctype": doctype, "processed": 0, "mode": cleanup_mode}

	if cleanup_mode == "Archive":
		return _archive_records(doctype, names)

	return _delete_records(doctype, names)


def _archive_records(doctype: str, names: list[str]) -> dict:
	archive_time = now()
	for name in names:
		frappe.db.set_value(
			doctype,
			name,
			{
				"archived": 1,
				"archived_on": archive_time,
				"cleanup_reason": "Archived by SMS retention cleanup.",
			},
			update_modified=False,
		)

	return {"doctype": doctype, "processed": len(names), "mode": "Archive"}


def _delete_records(doctype: str, names: list[str]) -> dict:
	deleted = 0
	failed = []
	for name in names:
		try:
			# SMS campaign recipients can link to SMS Logs. We do not silently clear that
			# link here; keep_campaign_sms_logs defaults to enabled so normal cleanup
			# avoids those records. If deletion fails, record it and continue.
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			deleted += 1
		except Exception as exc:
			failed.append({"name": name, "error": str(exc)})
			frappe.log_error(frappe.get_traceback(), f"{doctype} Cleanup Delete Error")

	return {"doctype": doctype, "processed": deleted, "failed": failed, "mode": "Delete"}


def _get_filters(doctype: str, *, settings, cleanup_mode: str) -> tuple[list[str], dict]:
	retention_days = _retention_days_for_doctype(doctype, settings=settings, cleanup_mode=cleanup_mode)
	cutoff_date = add_days(nowdate(), -retention_days)

	if cleanup_mode == "Archive":
		filters = ["date(creation) <= %(cutoff_date)s", "ifnull(archived, 0) = 0"]
	else:
		# Deletion is safest after records have first been archived. If archive mode
		# is disabled, this still only deletes records that match the configured
		# creation retention window.
		if cint(settings.get("archive_instead_of_delete")) and not cint(settings.get("delete_unarchived_sms_logs")):
			filters = ["date(archived_on) <= %(cutoff_date)s", "ifnull(archived, 0) = 1"]
		else:
			filters = ["date(creation) <= %(cutoff_date)s"]

	params = {"cutoff_date": cutoff_date}

	if doctype == "Rentals SMS Log":
		if cint(settings.get("keep_failed_sms_logs")):
			filters.append("ifnull(status, '') not in %(failed_statuses)s")
			params["failed_statuses"] = FAILED_STATUSES

		if cint(settings.get("keep_campaign_sms_logs")):
			filters.append("ifnull(sms_campaign, '') = ''")

	return filters, params


def _retention_days_for_doctype(doctype: str, *, settings, cleanup_mode: str) -> int:
	if cleanup_mode == "Delete" and cint(settings.get("archive_instead_of_delete")):
		return max(cint(settings.get("delete_archived_logs_after_days")) or DEFAULT_DELETE_ARCHIVED_AFTER_DAYS, 30)

	if doctype == "Rentals SMS Inbound Log":
		return max(cint(settings.get("inbound_log_retention_days")) or DEFAULT_INBOUND_RETENTION_DAYS, 30)

	return max(cint(settings.get("sms_log_retention_days")) or DEFAULT_SMS_RETENTION_DAYS, 30)


def _batch_size(settings) -> int:
	return min(max(cint(settings.get("cleanup_batch_size")) or DEFAULT_BATCH_SIZE, 50), 5000)
