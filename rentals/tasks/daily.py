import frappe
from frappe.utils import getdate, nowdate, add_days, add_months, add_years
from frappe import _

def check_expired_leases():
    today = nowdate()
    expired_leases = frappe.get_all(
        "Lease Agreement",
        filters={
            "end_date": ("<", today),
            "status": ["!=", "Expired"],
            "docstatus": 1
        },
        fields=["name"]
    )

    for lease in expired_leases:
        frappe.db.set_value("Lease Agreement", lease.name, "status", "Expired")
        frappe.logger().info(f"Lease {lease.name} marked as Expired.")

@frappe.whitelist()
def generate_sales_invoices(lease_name=None, override_billing_date=False):
    today = getdate(nowdate())
    invoice_names = []

    leases = [{"name": lease_name}] if lease_name else frappe.get_all(
        "Lease Agreement",
        filters={"status": "Active", "docstatus": 1},
        fields=["name"]
    )

    for lease in leases:
        lease_doc = frappe.get_doc("Lease Agreement", lease["name"])
        tenant = frappe.get_doc("Tenant", lease_doc.tenant)
        landlord = frappe.get_doc("Landlord", lease_doc.landlord)

        customer = tenant.customer
        currency = lease_doc.billing_currency
        company = landlord.company

        service_items = []
        utility_logs = []
        updated_services = []

        # Chargeable services
        for service in lease_doc.chargeable_services:
            if service.billing_cycle != "Once" and (override_billing_date or getdate(service.billing_date) == today):
                service_items.append({
                    "item_code": service.service,
                    "qty": 1,
                    "rate": service.rate,
                })
                updated_services.append(service)
            else:
                frappe.logger().info(f"Skipped service {service.service} for Lease {lease_doc.name}")

        # Utility logs
        logs = frappe.get_all(
            "Utility Bill Log",
            filters={"status": "Open", "lease_agreement": lease_doc.name},
            fields=["name"]
        )
        utility_logs = [frappe.get_doc("Utility Bill Log", l.name) for l in logs]

        # If no items, skip
        if not service_items and not utility_logs:
            continue

        # Create invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = customer
        invoice.company = company
        invoice.currency = currency
        invoice.posting_date = invoice.due_date = today
        invoice.remarks = f"Invoice for Lease Agreement {lease_doc.name} generated {'manually' if override_billing_date else 'automatically'} on {today}"
        invoice.custom_lease_agreement = lease_doc.name
        invoice.selling_price_list = frappe.db.get_value("Customer", customer, "default_price_list")

        # Add utility items
        for log in utility_logs:
            rates = frappe.get_all("Utility Rate", filters={
                "utility_provider": log.utility_provider,
                "utility": log.utility
            }, fields=["name", "rate_type", "flat_rate"])

            if not rates:
                frappe.logger().warn(f"No Utility Rate for {log.utility}")
                continue

            rate_type = rates[0]["rate_type"]

            if rate_type == "Flat":
                invoice.append("items", {
                    "item_code": log.utility,
                    "qty": log.units_used,
                    "rate": rates[0]["flat_rate"],
                    "description": f"{log.units_used} units @ flat rate"
                })
            elif rate_type == "Slab":
                rate_doc = frappe.get_doc("Utility Rate", rates[0]["name"])
                remaining_units = log.units_used
                for slab in sorted(rate_doc.slab_rate, key=lambda x: x.from_units):
                    if remaining_units <= 0:
                        break
                    from_u, to_u = slab.from_units, slab.to_units or float('inf')
                    slab_units = min(remaining_units, (to_u - from_u + 1) if to_u != float('inf') else remaining_units)
                    invoice.append("items", {
                        "item_code": log.utility,
                        "qty": slab_units,
                        "rate": slab.rate,
                        "description": f"{slab_units} units from {from_u} to {to_u if to_u != float('inf') else '∞'} @ {slab.rate}"
                    })
                    remaining_units -= slab_units

            log.status = "Billed"
            log.save(ignore_permissions=True)

        # Add service items
        for item in service_items:
            invoice.append("items", item)

        invoice.insert()
        invoice.submit()
        invoice_names.append(invoice.name)

        try:
            reconcile_customer_payments(customer, company)
        except Exception as e:
            frappe.logger().error(f"Auto-reconciliation failed for customer {customer}: {e}")

        # Update billing dates
        for service in updated_services:
            if service.billing_cycle == "Daily":
                service.billing_date = add_days(today, 1)
            elif service.billing_cycle == "Weekly":
                service.billing_date = add_days(today, 7)
            elif service.billing_cycle == "Monthly":
                service.billing_date = add_months(today, 1)
            elif service.billing_cycle == "Annually":
                service.billing_date = add_years(today, 1)

        lease_doc.save()

    return {
        "message": "Sales Invoices created successfully." if invoice_names else "No sales invoices were created.",
        "invoices": invoice_names
    }

def reconcile_customer_payments(customer, company):
    doc = frappe.new_doc("Payment Reconciliation")
    doc.party_type = "Customer"
    doc.party = customer
    doc.company = company
    doc.receivable_payable_account = frappe.get_value("Company", company, "default_receivable_account")

    # Populate payments and invoices
    doc.get_unreconciled_entries()

    if not doc.invoices or not doc.payments:
        frappe.logger().info(f"No unreconciled entries found for {customer}")
        return

    # Allocate entries
    doc.allocate_entries({
        "payments": [d.as_dict() for d in doc.payments],
        "invoices": [d.as_dict() for d in doc.invoices]
    })

    doc.save()
    doc.reconcile()
    frappe.logger().info(f"Reconciliation completed for {customer}")
