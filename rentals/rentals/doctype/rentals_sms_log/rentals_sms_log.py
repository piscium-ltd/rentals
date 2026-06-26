# Copyright (c) 2026, Piscium Solutions LTD and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from rentals.sms.utils import get_default_country_code, normalize_phone_number, normalize_sms_message, SMSValidationError


class RentalsSMSLog(Document):
	def validate(self):
		self._normalize_phone()
		self._normalize_message()

	def _normalize_phone(self):
		if self.normalized_phone:
			return

		try:
			self.normalized_phone = normalize_phone_number(
				self.recipient_phone,
				default_country_code=get_default_country_code(),
			)
		except SMSValidationError as exc:
			frappe.throw(_(str(exc)))

	def _normalize_message(self):
		try:
			self.message = normalize_sms_message(self.message)
		except SMSValidationError as exc:
			frappe.throw(_(str(exc)))
