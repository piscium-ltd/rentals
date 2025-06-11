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
        landlord_doc = frappe.get_doc("Landlord", lease_doc.landlord)
        company = landlord_doc.company
        tenant_doc = frappe.get_doc("Tenant", lease_doc.tenant)
        customer_name = tenant_doc.customer

        if customer_name not in customer_data:
            customer_data[customer_name] = {
                "currency": lease_doc.billing_currency,
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
        invoice.naming_series = "P.###.YY."
        invoice.company = company
        invoice.customer = customer_name
        invoice.currency = data["currency"]
        invoice.posting_date = invoice.due_date = today
        invoice.remarks = f"Consolidated invoice generated {'manually' if override_billing_date else 'automatically'} on {today}"

        # Add utility items
        for log_name in data["utility_logs"]:
            utility_log = frappe.get_doc("Utility Bill Log", log_name)
            utility_rate = frappe.get_all("Utility Rate", filters={
                "utility_provider": utility_log.utility_provider,
                "utility": utility_log.utility,
            }, fields=["name", "rate_type", "flat_rate"])

            if utility_rate:
                rate_type = utility_rate[0].get("rate_type")
                units = utility_log.units_used

                if rate_type == "Flat":
                    rate = utility_rate[0].get("flat_rate")
                    invoice.append("items", {
                        "item_code": utility_log.utility,
                        "qty": units,
                        "rate": rate,
                        "description": f"{units} units @ flat rate of {rate}",
                    })

                elif rate_type == "Slab":
                    rate_doc = frappe.get_doc("Utility Rate", utility_rate[0]["name"])
                    slab_rates = rate_doc.slab_rate

                    remaining_units = units

                    for slab in sorted(slab_rates, key=lambda x: x.from_units):
                        from_units = slab.from_units
                        to_units = slab.to_units or float('inf')
                        rate = slab.rate

                        if remaining_units <= 0:
                            break

                        if to_units == float('inf'):
                            slab_units = remaining_units
                        else:
                            slab_units = min(remaining_units, to_units - from_units + 1)

                        if slab_units > 0:
                            description = f"{slab_units} units from {from_units} to {'∞' if to_units == float('inf') else to_units} @ rate {rate}"
                            invoice.append("items", {
                                "item_code": utility_log.utility,
                                "qty": slab_units,
                                "rate": rate,
                                "description": description,
                            })
                            remaining_units -= slab_units

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