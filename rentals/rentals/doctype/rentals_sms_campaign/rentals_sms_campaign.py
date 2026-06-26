# Copyright (c) 2026, Piscium Solutions LTD and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from rentals.sms.campaign import FAILED_STATUSES, SENT_STATUSES, SKIPPED_STATUSES, resolve_campaign_recipients
from rentals.sms.utils import SMSValidationError, normalize_phone_number, normalize_sms_message


class RentalsSMSCampaign(Document):
	def validate(self):
		self._set_defaults()
		self._validate_target_filters()
		self._validate_message()
		self._normalize_child_recipients()
		self._sync_totals()

	def _set_defaults(self):
		if not self.status:
			self.status = "Draft"
		if not self.target_type:
			self.target_type = "All Active Tenants"
		if not self.lease_status and self.target_type in {
			"Tenants by Property",
			"Tenants by Landlord",
			"Tenants with Active Leases",
		}:
			self.lease_status = "Active"
		if self.exclude_opted_out_recipients in (None, ""):
			self.exclude_opted_out_recipients = 1

	def _validate_target_filters(self):
		if self.target_type == "Tenants by Property" and not self.property:
			frappe.throw(_("Property is required when Target Type is Tenants by Property."))
		if self.target_type == "Tenants by Landlord" and not self.landlord:
			frappe.throw(_("Landlord is required when Target Type is Tenants by Landlord."))
		if self.target_type == "Manual Numbers" and not self.manual_numbers and not self.recipients:
			frappe.throw(_("Manual Numbers or recipient rows are required when Target Type is Manual Numbers."))

	def _validate_message(self):
		try:
			self.message = normalize_sms_message(self.message)
		except SMSValidationError as exc:
			frappe.throw(_(str(exc)))

	def _normalize_child_recipients(self):
		seen: set[str] = set()
		for row in self.recipients or []:
			if not row.phone_number:
				continue

			try:
				row.normalized_phone = normalize_phone_number(row.phone_number)
			except SMSValidationError as exc:
				row.status = "InvalidPhoneNumber"
				row.error = str(exc)
				continue

			if row.normalized_phone in seen:
				row.status = "NotSent"
				row.error = _("Duplicate phone number in this campaign.")
				continue

			seen.add(row.normalized_phone)
			if not row.status:
				row.status = "Queued"

	def _sync_totals(self):
		valid_statuses = {"Queued", "Sending"} | SENT_STATUSES
		self.total_recipients = 0
		self.total_sent = 0
		self.total_failed = 0
		self.total_skipped = 0

		for row in self.recipients or []:
			status = row.status or "Queued"
			if status in valid_statuses:
				self.total_recipients += 1
			if status in SENT_STATUSES:
				self.total_sent += 1
			if status in FAILED_STATUSES:
				self.total_failed += 1
			if status in SKIPPED_STATUSES:
				self.total_skipped += 1

	def build_recipients(self):
		"""Document-level helper for scripts/tests. Desk button uses the whitelisted function."""
		recipients = resolve_campaign_recipients(self)
		self.set("recipients", [])
		for row in recipients:
			self.append("recipients", row)
		self._sync_totals()
		return recipients
