import frappe
from frappe.utils import nowdate

def check_expired_leases():
    today = nowdate()
    expired_leases = frappe.get_all("Lease Agreement",
        filters={
            "end_date": ("<", today),
            "status": ["!=", "Expired"]
        },
        fields=["name", "status"]
    )

    for lease in expired_leases:
        frappe.db.set_value("Lease Agreement", lease.name, "status", "Expired")
        frappe.db.commit()
        frappe.logger().info(f"Lease {lease.name} marked as Expired.")
