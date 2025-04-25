import frappe
from frappe.utils import nowdate, getdate, add_days, add_months, add_years

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

def get_utility_item_code_and_rate(utility, units_used, customer):
    """Fetch the correct utility item code and rate based on utility type, usage, and customer price list."""
    item_code = None
    if utility == "Electricity":
        if units_used <= 50:
            item_code = "Electricity-Up to 50 units"
        elif units_used <= 100:
            item_code = "Electricity-Above 50 up to 100 units"
        elif units_used <= 200:
            item_code = "Electricity-Above 100 up to 200 units"
        else:
            item_code = "Electricity-Above 200 units"
    elif utility == "Water":
        if units_used <= 50:
            item_code = "Water-Up to 50 units"
        elif units_used <= 100:
            item_code = "Water-Above 50 up to 100 units"
        elif units_used <= 200:
            item_code = "Water-Above 100 up to 200 units"
        else:
            item_code = "Water-Above 200 units"
    
    if item_code:
        # Fetch the item code and rate from Item Price
        item_price = frappe.get_all(
            "Item Price",
            filters={"item_code": item_code},
            fields=["price_list_rate", "item_code"]
        )

        if item_price:
            # Return the item_code and price_list_rate (rate)
            return item_price[0].item_code, item_price[0].price_list_rate

    return None, 0

def generate_sales_invoices():
    today = getdate(nowdate())
    active_leases = frappe.get_all(
        "Lease Agreement",
        filters={"status": "Active", "docstatus": 1},
        fields=["name"]
    )

    for lease in active_leases:
        lease_doc = frappe.get_doc("Lease Agreement", lease.name)
        tenant_doc = frappe.get_doc("Tenant", lease_doc.tenant)
        customer = frappe.get_doc("Customer", tenant_doc.customer)

        updated = False
        for service in lease_doc.chargeable_services:
            if getdate(service.billing_date) == today and service.billing_cycle != "Once":
                # Create Sales Invoice
                invoice = frappe.new_doc("Sales Invoice")
                invoice.customer = customer.name
                invoice.currency = lease_doc.billing_currency
                invoice.due_date = invoice.posting_date = today
                invoice.mode_of_payment = lease_doc.mode_of_payment
                invoice.remarks = f"Auto-generated invoice for lease {lease_doc.name} on {today}"

                # Get Utility Bill Logs
                utility_bill_logs = frappe.get_all(
                    "Utility Bill Log",
                    filters={"status": "Open", "customer": customer.name},
                    fields=["name"]
                )

                if utility_bill_logs:
                    for log in utility_bill_logs:
                        utility_bill_log = frappe.get_doc("Utility Bill Log", log.name)

                        # Get utility item code and rate based on usage and price list
                        item_code, rate = get_utility_item_code_and_rate(utility_bill_log.utility, utility_bill_log.units_used, customer.name)

                        if item_code:
                            # Add the utility bill item to the invoice
                            invoice.append("items", {
                                "item_code": item_code,
                                "qty": utility_bill_log.units_used,
                                "rate": rate,
                            })
                            utility_bill_log.status = "Billed"
                            utility_bill_log.save(ignore_permissions=True)

                # Add chargeable service to invoice
                invoice.append("items", {
                    "item_code": service.service,
                    "qty": 1,
                    "rate": service.rate,
                })

                invoice.insert()
                invoice.submit()
                frappe.logger().info(f"Sales Invoice created for Lease {lease_doc.name}")

                # Update next billing date based on the cycle
                if service.billing_cycle == "Daily":
                    service.billing_date = add_days(today, 1)
                elif service.billing_cycle == "Weekly":
                    service.billing_date = add_days(today, 7)
                elif service.billing_cycle == "Monthly":
                    service.billing_date = add_months(today, 1)
                elif service.billing_cycle == "Annually":
                    service.billing_date = add_years(today, 1)

                updated = True
            else:
                frappe.logger().info(f"Skipped service {service.service} for Lease {lease_doc.name}")

        if updated:
            lease_doc.save()
