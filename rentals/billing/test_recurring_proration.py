from datetime import date
from types import SimpleNamespace

from frappe.tests import UnitTestCase

from rentals.billing.invoice_generation import DuePeriod, _build_recurring_items


class TestRecurringProration(UnitTestCase):
    def _lease(self, *, prorate_last_invoice):
        service = SimpleNamespace(
            name="SVC-1",
            service="Internet",
            rate=3100,
            billing_cycle="Monthly",
        )
        return SimpleNamespace(
            rent_item="Rent",
            base_rental_amount=31000,
            billing_cycle="Monthly",
            end_date="2026-12-10",
            prorate_last_invoice=prorate_last_invoice,
            chargeable_services=[service],
        )

    def test_final_month_prorates_rent_and_monthly_fixed_service(self):
        period = DuePeriod(
            billing_date=date(2026, 12, 1),
            rent_due=True,
            service_names={"SVC-1"},
        )
        items = _build_recurring_items(self._lease(prorate_last_invoice=1), period)

        self.assertEqual(items[0]["item_code"], "Rent")
        self.assertEqual(items[0]["rate"], 9000)
        self.assertEqual(items[1]["item_code"], "Internet")
        self.assertEqual(items[1]["rate"], 900)
        self.assertIn("prorated through", items[0]["description"])

    def test_final_month_is_full_when_last_proration_is_off(self):
        period = DuePeriod(
            billing_date=date(2026, 12, 1),
            rent_due=True,
            service_names={"SVC-1"},
        )
        items = _build_recurring_items(self._lease(prorate_last_invoice=0), period)

        self.assertEqual(items[0]["rate"], 31000)
        self.assertEqual(items[1]["rate"], 3100)
