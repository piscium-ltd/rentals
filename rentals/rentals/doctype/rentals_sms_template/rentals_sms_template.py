# Copyright (c) 2026, Piscium Solutions LTD and contributors
# For license information, please see license.txt

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.document import Document

from rentals.sms.templates import render_template_message
from rentals.sms.utils import SMSValidationError, normalize_sms_message


class RentalsSMSTemplate(Document):
	def validate(self):
		self._set_defaults()
		self._validate_message()
		self._validate_sample_context()
		self._validate_single_default()
		self._set_preview_message()

	def _set_defaults(self):
		if not self.status:
			self.status = "Active"
		if not self.template_type:
			self.template_type = "Generic"

	def _validate_message(self):
		try:
			self.message = normalize_sms_message(self.message)
		except SMSValidationError as exc:
			frappe.throw(_(str(exc)))

	def _validate_sample_context(self):
		if not self.sample_context:
			return
		try:
			value = json.loads(self.sample_context)
		except Exception:
			frappe.throw(_("Sample Context must be valid JSON."))
		if not isinstance(value, dict):
			frappe.throw(_("Sample Context must be a JSON object."))

	def _validate_single_default(self):
		if not self.is_default or self.status != "Active" or not self.template_type:
			return

		existing = frappe.db.get_value(
			"Rentals SMS Template",
			{
				"template_type": self.template_type,
				"status": "Active",
				"is_default": 1,
				"name": ["!=", self.name or ""],
			},
			"name",
		)
		if existing:
			frappe.throw(_("Only one active default SMS template is allowed for {0}. Existing default: {1}").format(self.template_type, existing))

	def _set_preview_message(self):
		context = {}
		if self.sample_context:
			try:
				context = json.loads(self.sample_context)
			except Exception:
				context = {}

		try:
			self.preview_message = render_template_message(self.message, context)
		except Exception:
			self.preview_message = None
