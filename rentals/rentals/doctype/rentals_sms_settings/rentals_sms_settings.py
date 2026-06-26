# Copyright (c) 2026, Piscium Solutions LTD and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

from rentals.sms.utils import clean_phone_number


class RentalsSMSSettings(Document):
	def validate(self):
		self._set_defaults()
		self._validate_credentials_when_enabled()
		self._normalize_default_country_code()
		self._validate_reminder_settings()
		self._validate_cleanup_settings()

	def _set_defaults(self):
		if not self.environment:
			self.environment = "Sandbox"
		if not self.default_country_code:
			self.default_country_code = "254"

	def _validate_credentials_when_enabled(self):
		if not self.enabled:
			return

		if not self.username:
			frappe.throw(_("Africa's Talking username is required when SMS is enabled."))

		api_key = self.get_password("api_key") if hasattr(self, "get_password") else self.api_key
		if not api_key:
			frappe.throw(_("Africa's Talking API key is required when SMS is enabled."))

	def _normalize_default_country_code(self):
		country_code = clean_phone_number(self.default_country_code or "254").lstrip("+")
		if not country_code:
			frappe.throw(_("Default Country Code is required."))
		if len(country_code) < 1 or len(country_code) > 4:
			frappe.throw(_("Default Country Code must be 1 to 4 digits."))
		self.default_country_code = country_code

	def _validate_reminder_settings(self):
		self._validate_days_csv(
			fieldname="rent_due_reminder_days_before",
			label=_("Rent Due Reminder Days Before"),
			allow_zero=True,
		)
		self._validate_days_csv(
			fieldname="overdue_invoice_reminder_days_after",
			label=_("Overdue Invoice Reminder Days After"),
			allow_zero=False,
		)
		self._validate_days_csv(
			fieldname="lease_expiry_reminder_days_before",
			label=_("Lease Expiry Reminder Days Before"),
			allow_zero=True,
		)

		if cint(self.reminder_sms_limit_per_run or 0) <= 0:
			self.reminder_sms_limit_per_run = 500

	def _validate_cleanup_settings(self):
		if cint(self.sms_log_retention_days or 0) < 30:
			self.sms_log_retention_days = 365

		if cint(self.inbound_log_retention_days or 0) < 30:
			self.inbound_log_retention_days = 365

		if cint(self.delete_archived_logs_after_days or 0) < 30:
			self.delete_archived_logs_after_days = 730

		batch_size = cint(self.cleanup_batch_size or 0)
		if batch_size <= 0:
			self.cleanup_batch_size = 1000
		elif batch_size < 50:
			self.cleanup_batch_size = 50
		elif batch_size > 5000:
			self.cleanup_batch_size = 5000

	def _validate_days_csv(self, *, fieldname: str, label: str, allow_zero: bool):
		value = (self.get(fieldname) or "").strip()
		if not value:
			return

		clean_values = []
		for raw_part in value.replace(";", ",").replace("|", ",").split(","):
			part = raw_part.strip()
			if not part:
				continue
			if not part.isdigit():
				frappe.throw(_("{0} must contain only comma-separated whole numbers.").format(label))

			days = cint(part)
			if days == 0 and not allow_zero:
				frappe.throw(_("{0} must be greater than zero.").format(label))
			if days < 0:
				frappe.throw(_("{0} cannot contain negative values.").format(label))

			clean_values.append(str(days))

		# Deduplicate while preserving order.
		seen = set()
		deduped = []
		for item in clean_values:
			if item in seen:
				continue
			seen.add(item)
			deduped.append(item)

		self.set(fieldname, ",".join(deduped))

