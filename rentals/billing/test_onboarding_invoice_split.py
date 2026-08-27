from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests import UnitTestCase

import rentals.api as rentals_api


class TestOnboardingInvoiceSplit(UnitTestCase):
    def test_split_copies_prorated_sales_order_rates(self):
        lease = SimpleNamespace(
            security_deposits=[SimpleNamespace(security_type="Deposit")],
            chargeable_services=[SimpleNamespace(service="Internet", billing_cycle="Monthly")],
            rent_item="Rent",
            base_rental_amount=30000,
        )
        sales_order = SimpleNamespace(
            name="SO-TEST",
            per_billed=0,
            items=[
                SimpleNamespace(name="SOI-DEP", item_code="Deposit", qty=1, rate=30000),
                SimpleNamespace(name="SOI-RENT", item_code="Rent", qty=1, rate=5000),
                SimpleNamespace(name="SOI-NET", item_code="Internet", qty=1, rate=500),
            ],
        )

        with (
            patch.object(rentals_api.frappe, "get_doc", return_value=sales_order),
            patch.object(
                rentals_api,
                "create_sales_invoice",
                side_effect=["SINV-DEPOSIT", "SINV-RECURRING"],
            ) as create_invoice,
        ):
            created = rentals_api.handle_sales_order_invoices(
                lease,
                sales_order.name,
                "Customer",
                "Company",
                "KES",
                "Customer Price List",
            )

        self.assertEqual(created, ["SINV-DEPOSIT", "SINV-RECURRING"])
        deposit_items = create_invoice.call_args_list[0].args[3]
        recurring_items = create_invoice.call_args_list[1].args[3]

        self.assertEqual(deposit_items[0]["rate"], 30000)
        self.assertEqual(recurring_items[0]["rate"], 5000)
        self.assertEqual(recurring_items[1]["rate"], 500)
        self.assertEqual(recurring_items[0]["so_detail"], "SOI-RENT")
        self.assertEqual(recurring_items[1]["so_detail"], "SOI-NET")
