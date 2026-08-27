# Copyright (c) 2025, Piscium Solutions LTD and Contributors
# See license.txt

from unittest.mock import patch

from frappe.tests import IntegrationTestCase, UnitTestCase

from rentals.rentals.doctype.property.property import Property


EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class _AssetMeta:
    def __init__(self, fields):
        self.fields = set(fields)

    def has_field(self, fieldname):
        return fieldname in self.fields


class _PropertyForPayload:
    acquisition_cost = 12_500_000
    acquisition_date = "2026-01-10"
    available_for_use_date = "2026-02-01"
    accounting_model = "Cost Model"
    calculate_depreciation = 1
    depreciation_frequency = "Annual"
    useful_life_years = 40
    residual_value = 500_000

    def _get_depreciation_frequency_months(self):
        return Property._get_depreciation_frequency_months(self)

    def _get_total_depreciations(self, frequency_months):
        return Property._get_total_depreciations(self, frequency_months)


class UnitTestProperty(UnitTestCase):
    def test_cost_model_asset_payload_sets_net_purchase_amount(self):
        prop = _PropertyForPayload()
        meta = _AssetMeta({"asset_type"})

        with patch("rentals.rentals.doctype.property.property.frappe.get_meta", return_value=meta):
            payload = Property._build_asset_payload(
                prop,
                company="Test Company",
                asset_category="Investment Property",
                asset_location="Property Site",
            )

        self.assertEqual(payload["net_purchase_amount"], 12_500_000)
        self.assertEqual(payload["asset_type"], "Existing Asset")
        self.assertEqual(payload["calculate_depreciation"], 1)
        self.assertEqual(payload["finance_books"][0]["total_number_of_depreciations"], 40)
        self.assertEqual(payload["finance_books"][0]["frequency_of_depreciation"], 12)

    def test_fair_value_model_uses_acquisition_cost_without_depreciation(self):
        prop = _PropertyForPayload()
        prop.accounting_model = "Fair Value Model"
        prop.calculate_depreciation = 0
        prop.current_fair_value = 20_000_000
        meta = _AssetMeta({"asset_type", "gross_purchase_amount"})

        with patch("rentals.rentals.doctype.property.property.frappe.get_meta", return_value=meta):
            payload = Property._build_asset_payload(
                prop,
                company="Test Company",
                asset_category="Investment Property",
                asset_location="Property Site",
            )

        self.assertEqual(payload["net_purchase_amount"], 12_500_000)
        self.assertEqual(payload["gross_purchase_amount"], 12_500_000)
        self.assertEqual(payload["calculate_depreciation"], 0)
        self.assertNotIn("finance_books", payload)

    def test_monthly_depreciation_uses_full_useful_life(self):
        prop = _PropertyForPayload()
        prop.depreciation_frequency = "Monthly"

        frequency = Property._get_depreciation_frequency_months(prop)
        total = Property._get_total_depreciations(prop, frequency)

        self.assertEqual(frequency, 1)
        self.assertEqual(total, 480)


class IntegrationTestProperty(IntegrationTestCase):
    pass
