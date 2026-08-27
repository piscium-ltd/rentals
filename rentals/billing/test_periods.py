from frappe.tests import UnitTestCase

from rentals.billing.periods import (
    get_final_proration_factor,
    get_initial_billing_date,
    get_initial_charge_amount,
    get_initial_proration_factor,
    get_recurring_charge_amount,
)


class TestBillingPeriods(UnitTestCase):
    def test_prorated_monthly_start_moves_recurring_billing_to_first(self):
        self.assertEqual(
            str(get_initial_billing_date("2026-09-25", "Monthly", True)),
            "2026-10-01",
        )

    def test_non_prorated_monthly_start_keeps_anniversary_billing(self):
        self.assertEqual(
            str(get_initial_billing_date("2026-09-25", "Monthly", False)),
            "2026-10-25",
        )

    def test_first_proration_uses_agreed_boundary_day_convention(self):
        factor = get_initial_proration_factor(
            start_date="2026-09-25",
            cycle="Monthly",
            prorate_first_invoice=True,
        )
        self.assertAlmostEqual(factor, 5 / 30)
        self.assertEqual(
            get_initial_charge_amount(
                30000,
                start_date="2026-09-25",
                cycle="Monthly",
                prorate_first_invoice=True,
            ),
            5000,
        )

    def test_first_day_of_month_is_full_initial_month(self):
        self.assertEqual(
            get_initial_proration_factor(
                start_date="2026-09-01",
                cycle="Monthly",
                prorate_first_invoice=True,
            ),
            1,
        )

    def test_first_and_last_can_be_same_partial_period(self):
        factor = get_initial_proration_factor(
            start_date="2026-09-25",
            cycle="Monthly",
            prorate_first_invoice=True,
            end_date="2026-09-28",
            prorate_last_invoice=True,
        )
        self.assertAlmostEqual(factor, 3 / 30)
        self.assertEqual(
            get_initial_charge_amount(
                30000,
                start_date="2026-09-25",
                cycle="Monthly",
                prorate_first_invoice=True,
                end_date="2026-09-28",
                prorate_last_invoice=True,
            ),
            3000,
        )

    def test_last_proration_on_calendar_month(self):
        factor = get_final_proration_factor(
            period_start="2026-12-01",
            cycle="Monthly",
            end_date="2026-12-10",
            prorate_last_invoice=True,
        )
        self.assertAlmostEqual(factor, 9 / 31)
        self.assertAlmostEqual(
            get_recurring_charge_amount(
                31000,
                period_start="2026-12-01",
                cycle="Monthly",
                end_date="2026-12-10",
                prorate_last_invoice=True,
            ),
            9000,
        )

    def test_ending_on_last_day_is_full_month(self):
        self.assertEqual(
            get_final_proration_factor(
                period_start="2026-12-01",
                cycle="Monthly",
                end_date="2026-12-31",
                prorate_last_invoice=True,
            ),
            1,
        )

    def test_short_anniversary_lease_uses_last_proration_on_onboarding(self):
        factor = get_initial_proration_factor(
            start_date="2026-09-25",
            cycle="Monthly",
            prorate_first_invoice=False,
            end_date="2026-10-10",
            prorate_last_invoice=True,
        )
        self.assertAlmostEqual(factor, 15 / 30)

    def test_non_monthly_charges_are_not_prorated(self):
        self.assertEqual(
            get_initial_proration_factor(
                start_date="2026-09-25",
                cycle="Quarterly",
                prorate_first_invoice=True,
                end_date="2026-10-10",
                prorate_last_invoice=True,
            ),
            1,
        )
        self.assertEqual(
            get_final_proration_factor(
                period_start="2026-10-01",
                cycle="Quarterly",
                end_date="2026-10-10",
                prorate_last_invoice=True,
            ),
            1,
        )
