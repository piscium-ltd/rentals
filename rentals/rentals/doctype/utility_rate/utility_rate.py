# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class UtilityRate(Document):
	def before_validate(self):
		"""Keep only the fields that belong to the selected rate mode.

		Desk clears these values immediately when the selector changes, but this
		server-side normalization is the source of truth for API/import/background
		saves as well.
		"""
		if self.rate_type == "Flat":
			self.set("slab_rate", [])
		elif self.rate_type == "Slab":
			self.flat_rate = None

	def validate(self):
		self._validate_rate_configuration()
		self._validate_unique_provider()

	def _validate_unique_provider(self):
		"""Reject a second rate for the same provider without matching self on edit."""
		if not self.utility_provider:
			return

		filters = {"utility_provider": self.utility_provider}
		if not self.is_new() and self.name:
			filters["name"] = ["!=", self.name]

		existing_rate_name = frappe.db.get_value("Utility Rate", filters, "name")
		if not existing_rate_name:
			return

		rate_url = frappe.utils.get_url(f"app/utility-rate/{existing_rate_name}")
		frappe.throw(
			_(
				"This Utility Provider already has a rate. Please update the existing rate: "
				"<a href='{0}'>{1}</a>."
			).format(rate_url, existing_rate_name)
		)

	def _validate_rate_configuration(self):
		if self.rate_type == "Flat":
			self._validate_flat_rate()
		elif self.rate_type == "Slab":
			self._validate_slab_rates()

	def _validate_flat_rate(self):
		if self.flat_rate in (None, ""):
			frappe.throw(_("Flat Rate is required when Rate Type is Flat."))

		if flt(self.flat_rate) < 0:
			frappe.throw(_("Flat Rate cannot be negative."))

	def _validate_slab_rates(self):
		rows = list(self.slab_rate or [])
		if not rows:
			frappe.throw(_("At least one Slab Rate row is required when Rate Type is Slab."))

		normalized_rows = []
		for row_number, row in enumerate(rows, start=1):
			from_units = row.from_units
			to_units = row.to_units
			rate = row.rate

			if from_units in (None, ""):
				frappe.throw(_("From Units is required in Slab Rate row {0}.").format(row_number))
			if flt(from_units) < 0:
				frappe.throw(_("From Units cannot be negative in Slab Rate row {0}.").format(row_number))

			if rate in (None, ""):
				frappe.throw(_("Rate is required in Slab Rate row {0}.").format(row_number))
			if flt(rate) < 0:
				frappe.throw(_("Rate cannot be negative in Slab Rate row {0}.").format(row_number))

			open_ended = to_units in (None, "")
			if not open_ended and flt(to_units) < flt(from_units):
				frappe.throw(
					_("To Units must be greater than or equal to From Units in Slab Rate row {0}.").format(
						row_number
					)
				)

			normalized_rows.append(
				{
					"row_number": row_number,
					"from_units": flt(from_units),
					"to_units": None if open_ended else flt(to_units),
				}
			)

		self._validate_slab_ranges(normalized_rows)

	def _validate_slab_ranges(self, rows):
		ordered_rows = sorted(rows, key=lambda row: row["from_units"])

		for index, row in enumerate(ordered_rows):
			if row["to_units"] is None and index != len(ordered_rows) - 1:
				frappe.throw(
					_("Open-ended Slab Rate row {0} must be the final slab.").format(row["row_number"])
				)

			if index == 0:
				continue

			previous = ordered_rows[index - 1]
			if previous["to_units"] is None:
				frappe.throw(
					_("Slab Rate row {0} overlaps an earlier open-ended slab.").format(row["row_number"])
				)

			if row["from_units"] <= previous["to_units"]:
				frappe.throw(
					_("Slab Rate row {0} overlaps Slab Rate row {1}.").format(
						row["row_number"], previous["row_number"]
					)
				)
