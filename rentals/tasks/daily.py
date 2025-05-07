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
@frappe.whitelist()
def generate_sales_invoices(lease_name=None, override_billing_date=False):
    today = getdate(nowdate())
    invoice_names = []

    if lease_name:
        leases = [{"name": lease_name}]
    else:
        leases = frappe.get_all(
            "Lease Agreement",
            filters={"status": "Active", "docstatus": 1},
            fields=["name"]
        )

    customer_data = {}
    for lease in leases:
        lease_doc = frappe.get_doc("Lease Agreement", lease["name"])
        tenant_doc = frappe.get_doc("Tenant", lease_doc.tenant)
        customer_name = tenant_doc.customer

        if customer_name not in customer_data:
            customer_data[customer_name] = {
                "currency": lease_doc.billing_currency,
                "mode_of_payment": lease_doc.mode_of_payment,
                "items": [],
                "lease_updates": [],
                "utility_logs": [],
            }
        updated = False

        # Add chargeable services
        for service in lease_doc.chargeable_services:
            if service.billing_cycle == "Once":
                continue  

            if override_billing_date or getdate(service.billing_date) == today:
                customer_data[customer_name]["items"].append({
                    "item_code": service.service,
                    "qty": 1,
                    "rate": service.rate,
                })
                customer_data[customer_name]["lease_updates"].append((lease_doc, service))
                updated = True
            else:
                frappe.logger().info(f"Skipped service {service.service} for Lease {lease_doc.name} due to billing date mismatch")
        # Collect open utility logs
        utility_bill_logs = frappe.get_all(
            "Utility Bill Log",
            filters={"status": "Open", "customer": customer_name},
            fields=["name"]
        )
        for log in utility_bill_logs:
            customer_data[customer_name]["utility_logs"].append(log["name"])

        if updated:
            lease_doc.save()

    # Generate one invoice per customer
    for customer_name, data in customer_data.items():
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = customer_name
        invoice.currency = data["currency"]
        invoice.posting_date = invoice.due_date = today
        invoice.mode_of_payment = data["mode_of_payment"]
        invoice.remarks = f"Consolidated invoice generated {'manually' if override_billing_date else 'automatically'} on {today}"

        # Add utility items
        for log_name in data["utility_logs"]:
            utility_log = frappe.get_doc("Utility Bill Log", log_name)
            item_code, rate = get_utility_item_code_and_rate(
                utility_log.utility,
                utility_log.units_used,
                customer_name
            )
            if item_code:
                invoice.append("items", {
                    "item_code": item_code,
                    "qty": utility_log.units_used,
                    "rate": rate,
                })
                utility_log.status = "Billed"
                utility_log.save(ignore_permissions=True)
        # Add service items
        for item in data["items"]:
            invoice.append("items", item)

        if invoice.items:
            invoice.insert()
            invoice.submit()
            frappe.logger().info(f"Sales Invoice created for customer {customer_name} with {len(invoice.items)} items.")
            invoice_names.append(invoice.name)  

        # Update next billing date for services
        for lease_doc, service in data["lease_updates"]:
            if service.billing_cycle == "Daily":
                service.billing_date = add_days(today, 1)
            elif service.billing_cycle == "Weekly":
                service.billing_date = add_days(today, 7)
            elif service.billing_cycle == "Monthly":
                service.billing_date = add_months(today, 1)
            elif service.billing_cycle == "Annually":
                service.billing_date = add_years(today, 1)
            lease_doc.save()

    if invoice_names:
        return {
            "message": "Sales Invoice created successfully.",
            "invoices": invoice_names
        }

    else:
        return {
            "message": "No sales invoices were created.",
            "invoices": []
        }