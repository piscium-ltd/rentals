import frappe
from frappe.utils import getdate, nowdate, add_days, add_months
from frappe import _

def check_expired_leases():
    """Mark leases as expired based on end date."""
    today = nowdate()
    expired_leases = frappe.get_all(
        "Lease Agreement",
        filters={"end_date": ("<", today), "status": ["!=", "Expired"], "docstatus": 1},
        fields=["name"]
    )

    for lease in expired_leases:
        frappe.db.set_value("Lease Agreement", lease.name, "status", "Expired")
        frappe.logger().info(f"Lease {lease.name} marked as Expired.")

@frappe.whitelist()
def generate_sales_invoices(lease_name=None, override_billing_date=False):
    """Generate sales invoices for leases if rent or services are due."""
    today = getdate(nowdate())
    leases = get_target_leases(lease_name)
    created_invoices = []

    for lease in leases:
        lease_doc = frappe.get_doc("Lease Agreement", lease["name"])
        invoice_items, updated_services = get_invoice_items(lease_doc, today, override_billing_date)

        add_utility_bills_to_invoice(lease_doc, invoice_items)

        if not invoice_items:
            frappe.logger().info(f"No items to invoice for lease {lease_doc.name}")
            continue

        invoice = create_sales_invoice(lease_doc, invoice_items, today, override_billing_date)
        created_invoices.append(invoice.name)

        attempt_reconciliation(lease_doc.customer, lease_doc.company)

        update_billing_dates(lease_doc, updated_services, today, override_billing_date)
        lease_doc.save()

    return {
        "message": "Sales Invoice(s) generated successfully." if created_invoices else "No Sales invoices were created.",
        "invoices": created_invoices
    }

def get_target_leases(lease_name):
    """Return list of leases to process."""
    if lease_name:
        return [{"name": lease_name}]
    return frappe.get_all("Lease Agreement", filters={"status": "Active", "docstatus": 1}, fields=["name"])

def get_invoice_items(lease_doc, today, override_billing_date):
    """Return rent and chargeable services that are due."""
    invoice_items = []
    updated_services = []

    # Rent
    if lease_doc.rent_item and (override_billing_date or getdate(lease_doc.billing_date) == today):
        invoice_items.append({
            "item_code": lease_doc.rent_item,
            "qty": 1,
            "rate": lease_doc.base_rental_amount
        })

    # Services
    for service in lease_doc.chargeable_services:
        if override_billing_date or getdate(service.billing_date) == today:
            invoice_items.append({
                "item_code": service.service,
                "qty": 1,
                "rate": service.rate
            })
            updated_services.append(service)
        else:
            frappe.logger().info(f"Skipped service {service.service} for Lease {lease_doc.name}")

    return invoice_items, updated_services

def add_utility_bills_to_invoice(lease_doc, invoice_items):
    """Add utility bill items to the invoice."""
    utility_logs = frappe.get_all(
        "Utility Bill Log",
        filters={"status": "Open", "lease_agreement": lease_doc.name},
        fields=["name"]
    )

    for log in utility_logs:
        log_doc = frappe.get_doc("Utility Bill Log", log.name)
        rate = frappe.db.get_value(
            "Utility Rate",
            filters={"utility_provider": log_doc.utility_provider, "utility": log_doc.utility},
            fieldname=["name", "rate_type", "flat_rate"],
            as_dict=True
        )

        if not rate:
            frappe.logger().warn(f"No Utility Rate found for {log_doc.utility}")
            continue

        if rate["rate_type"] == "Flat":
            invoice_items.append({
                "item_code": log.utility,
                "qty": log.units_used,
                "rate": rate["flat_rate"],
                "description": f"{log.units_used} units @ flat rate"
            })

        elif rate["rate_type"] == "Slab":
            add_slab_items(log_doc, rate["name"], invoice_items)

        log_doc.status = "Billed"
        log_doc.save(ignore_permissions=True)

def add_slab_items(log_doc, rate_name, invoice_items):
    """Add slab-based utility billing."""
    rate_doc = frappe.get_doc("Utility Rate", rate_name)
    remaining_units = log_doc.units_used

    for slab in sorted(rate_doc.slab_rate, key=lambda x: x.from_units):
        if remaining_units <= 0:
            break

        from_u = slab.from_units
        to_u = slab.to_units or float("inf")
        slab_units = min(remaining_units, (to_u - from_u + 1) if to_u != float("inf") else remaining_units)

        invoice_items.append({
            "item_code": log_doc.utility,
            "qty": slab_units,
            "rate": slab.rate,
            "description": f"{slab_units} units from {from_u} to {to_u if to_u != float('inf') else '∞'} @ {slab.rate}"
        })

        remaining_units -= slab_units

def create_sales_invoice(lease_doc, invoice_items, today, override):
    """Create and submit the Sales Invoice."""
    invoice = frappe.get_doc({
        "doctype": "Sales Invoice",
        "customer": lease_doc.customer,
        "company": lease_doc.company,
        "due_date": today,
        "posting_date": today,
        "set_posting_time": 1,
        "debit_to": frappe.get_value("Company", lease_doc.company, "default_receivable_account"),
        "currency": lease_doc.billing_currency,
        "selling_price_list": frappe.db.get_value("Customer", lease_doc.customer, "default_price_list"),
        "custom_lease_agreement": lease_doc.name,
        "items": invoice_items,
        "remarks": f"Invoice for Lease Agreement {lease_doc.name} generated {'manually' if override else 'automatically'} on {today}"
    })
    invoice.insert()
    invoice.submit()
    return invoice

def attempt_reconciliation(customer, company):
    """Auto-reconcile customer payments."""
    try:
        doc = frappe.new_doc("Payment Reconciliation")
        doc.party_type = "Customer"
        doc.party = customer
        doc.company = company
        doc.receivable_payable_account = frappe.get_value("Company", company, "default_receivable_account")
        doc.get_unreconciled_entries()

        if not doc.invoices or not doc.payments:
            frappe.logger().info(f"No unreconciled entries for customer {customer}")
            return

        doc.allocate_entries({
            "payments": [d.as_dict() for d in doc.payments],
            "invoices": [d.as_dict() for d in doc.invoices]
        })

        doc.save()
        doc.reconcile()
        frappe.logger().info(f"Reconciliation completed for customer {customer}")
    except Exception as e:
        frappe.logger().error(f"Auto-reconciliation failed for customer {customer}: {e}")

def update_billing_dates(lease_doc, services, today, override):
    """Update billing dates for rent and services."""
    # Chargeable services
    for service in services:
        service.billing_date = get_next_billing_date(today, service.billing_cycle)

    # Rent
    if lease_doc.rent_item and (override or getdate(lease_doc.billing_date) == today):
        lease_doc.billing_date = get_next_billing_date(today, lease_doc.billing_cycle)

def get_next_billing_date(current_date, cycle):
    """Return the next billing date based on the cycle."""
    return {
        "Daily": add_days(current_date, 1),
        "Monthly": add_months(current_date, 1),
        "Quarterly": add_months(current_date, 3),
        "Annually": add_months(current_date, 12)
    }.get(cycle, current_date)
