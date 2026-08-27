# Copyright (c) 2025, Piscium Solutions LTD and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError
from frappe.tests import IntegrationTestCase, UnitTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]


class UnitTestUtilityRate(UnitTestCase):
	def _new_rate(self, rate_type, flat_rate=None, slabs=None):
		doc = frappe.get_doc(
			{
				"doctype": "Utility Rate",
				"utility_provider": "Test Utility Provider",
				"rate_type": rate_type,
				"flat_rate": flat_rate,
			}
		)
		for slab in slabs or []:
			doc.append("slab_rate", slab)
		return doc

	def test_flat_mode_clears_slab_rows(self):
		doc = self._new_rate(
			"Flat",
			flat_rate=25,
			slabs=[{"from_units": 1, "to_units": 10, "rate": 5}],
		)

		doc.before_validate()

		self.assertEqual(doc.slab_rate, [])
		self.assertEqual(doc.flat_rate, 25)

	def test_slab_mode_clears_flat_rate(self):
		doc = self._new_rate(
			"Slab",
			flat_rate=25,
			slabs=[{"from_units": 1, "to_units": 10, "rate": 5}],
		)

		doc.before_validate()

		self.assertIsNone(doc.flat_rate)
		self.assertEqual(len(doc.slab_rate), 1)

	def test_slab_mode_requires_rows(self):
		doc = self._new_rate("Slab")

		with self.assertRaises(ValidationError):
			doc._validate_rate_configuration()

	def test_slab_ranges_cannot_overlap(self):
		doc = self._new_rate(
			"Slab",
			slabs=[
				{"from_units": 1, "to_units": 10, "rate": 5},
				{"from_units": 10, "to_units": 20, "rate": 7},
			],
		)

		with self.assertRaises(ValidationError):
			doc._validate_rate_configuration()

	def test_open_ended_slab_must_be_final(self):
		doc = self._new_rate(
			"Slab",
			slabs=[
				{"from_units": 1, "rate": 5},
				{"from_units": 11, "to_units": 20, "rate": 7},
			],
		)

		with self.assertRaises(ValidationError):
			doc._validate_rate_configuration()

	def test_valid_slab_configuration(self):
		doc = self._new_rate(
			"Slab",
			slabs=[
				{"from_units": 1, "to_units": 10, "rate": 5},
				{"from_units": 11, "rate": 7},
			],
		)

		doc._validate_rate_configuration()

	def test_existing_document_excludes_itself_from_duplicate_lookup(self):
		doc = self._new_rate("Flat", flat_rate=25)
		doc.name = "Test Utility Provider"

		with (
			patch.object(doc, "is_new", return_value=False),
			patch.object(frappe.db, "get_value", return_value=None) as get_value,
		):
			doc._validate_unique_provider()

		get_value.assert_called_once_with(
			"Utility Rate",
			{
				"utility_provider": "Test Utility Provider",
				"name": ["!=", "Test Utility Provider"],
			},
			"name",
		)


class IntegrationTestUtilityRate(IntegrationTestCase):
	"""Integration coverage is provided by the app's normal DocType save tests."""

	pass
