import frappe
from frappe import _
from frappe.utils import nowdate, getdate

def check_expired_leases():
    today = nowdate()
    expired_leases = frappe.get_all(
        "Lease Agreement",
        filters={
            "end_date": ("<", today),
            "status": ["!=", "Expired"]
        },
        fields=["name", "status"]
    )

    for lease in expired_leases:
        frappe.db.set_value("Lease Agreement", lease.name, "status", "Expired")
        frappe.logger().info(f"Lease {lease.name} marked as Expired.")

def generate_sales_invoices():
    lease_agreements = frappe.get_all(
        "Lease Agreement",
        filters={"status": "Active"},
        fields=["name", "tenant", "landlord", "billing_currency", "mode_of_payment"]
    )

    for lease in lease_agreements:
        lease_doc = frappe.get_doc("Lease Agreement", lease.name)
        for service in lease_doc.chargeable_services:
            billing_date = getdate(service.billing_date)
            today = getdate(nowdate())
            if billing_date == today:
                item_doc = frappe.get_doc("Item", service.service)
                tenant_doc = frappe.get_doc("Tenant", lease_doc.tenant)
                customer = frappe.get_doc("Customer", tenant_doc.customer)
                invoice = frappe.new_doc("Sales Invoice")
                invoice.customer = customer.name
                invoice.currency = lease_doc.billing_currency
                invoice.due_date = nowdate()
                invoice.posting_date = nowdate()
                invoice.mode_of_payment = lease_doc.mode_of_payment

                invoice.append("items", {
                    "item_code": service.service,
                    "item_name": item_doc.item_name,
                    "qty": 1,
                    "rate": service.rate,
                })

                invoice.insert()
                invoice.submit()
                frappe.msgprint(f"Sales Invoice created for Lease {lease_doc.name}")
# To Do
# 1. Update billing_date for chargeable_services
# 2. Add utility logs to sales invoice
# 3. Make code better