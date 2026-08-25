import frappe
from frappe.utils import nowdate

from rentals.billing.invoice_generation import (
    generate_sales_invoices,
    get_next_billing_date,
    preview_invoice_generation,
)


def check_expired_leases():
    """Mark leases as expired based on end date."""
    today = nowdate()
    expired_leases = frappe.get_all(
        "Lease Agreement",
        filters={"end_date": ("<", today), "status": ["!=", "Expired"], "docstatus": 1},
        fields=["name"],
    )

    for lease in expired_leases:
        frappe.db.set_value("Lease Agreement", lease.name, "status", "Expired")
        frappe.logger().info("Lease %s marked as Expired.", lease.name)
