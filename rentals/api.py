import frappe
from frappe.utils import getdate, nowdate

@frappe.whitelist(allow_guest=True)
def bank_payment_webhook(account_number, amount):
    amount = float(amount)
    today = getdate(nowdate())

    lease = frappe.get_doc("Lease Agreement", account_number)
    customer = frappe.get_value("Tenant", lease.tenant, "customer")
    company = frappe.get_value("Landlord", lease.landlord, "company")
    price_list = frappe.db.get_value("Customer", customer, "default_price_list")
    currency = lease.billing_currency

    if not customer or not company:
        frappe.throw("Customer or Company not found.")

    # Check for Sales Order (Onboarding Payment)
    sales_order = frappe.db.get_value("Sales Order", {"custom_lease_agreement": lease.name}, "name")
    created_invoices = []

    if sales_order:
        so_doc = frappe.get_doc("Sales Order", sales_order)

        if so_doc.per_billed < 100:
            once_items = []
            recurring_items = []

            for row in lease.chargeable_services:
                item = {
                    "item_code": row.service,
                    "qty": 1,
                    "rate": row.rate,
                    "description": row.billing_cycle,
                    "sales_order": so_doc.name,
                    "so_detail": frappe.db.get_value("Sales Order Item",{"parent": so_doc.name, "item_code": row.service},"name")
                }
                if row.billing_cycle == "Once":
                    once_items.append(item)
                else:
                    recurring_items.append(item)

            # Create Deposit Certificate
            if once_items:
                invoice1 = frappe.get_doc({
                    "doctype": "Sales Invoice",
                    "customer": customer,
                    "company": company,
                    "currency": currency,
                    "posting_date": today,
                    "custom_lease_agreement": lease.name,
                    "selling_price_list": price_list,
                    "items": once_items,
                    "remarks": "Deposit Certificate for onboarding"
                })
                invoice1.insert()
                invoice1.submit()
                created_invoices.append(invoice1.name)

            # Create Recurring Services Invoice
            if recurring_items:
                invoice2 = frappe.get_doc({
                    "doctype": "Sales Invoice",
                    "customer": customer,
                    "company": company,
                    "currency": currency,
                    "posting_date": today,
                    "custom_lease_agreement": lease.name,
                    "selling_price_list": price_list,
                    "items": recurring_items,
                    "remarks": "Initial recurring services invoice"
                })
                invoice2.insert()
                invoice2.submit()
                created_invoices.append(invoice2.name)

    # Step 2: Pay outstanding invoices for this lease
    invoices = frappe.get_all("Sales Invoice", filters={
        "customer": customer,
        "custom_lease_agreement": lease.name,
        "outstanding_amount": [">", 0],
        "docstatus": 1
    }, fields=["name", "outstanding_amount"])

    remaining_amount = amount
    references = []

    for inv in invoices:
        if remaining_amount <= 0:
            break
        to_allocate = min(inv.outstanding_amount, remaining_amount)
        references.append({
            "reference_doctype": "Sales Invoice",
            "reference_name": inv.name,
            "allocated_amount": to_allocate
        })
        remaining_amount -= to_allocate

    # Step 3: Create Payment Entry
    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = "Receive"
    pe.party_type = "Customer"
    pe.party = customer
    pe.posting_date = today
    pe.paid_amount = amount
    pe.received_amount = amount
    pe.unallocated_amount = remaining_amount if remaining_amount > 0 else 0
    pe.company = company
    pe.target_exchange_rate = 1.0 
    pe.currency = currency
    pe.paid_to = frappe.get_cached_value("Company", company, "default_bank_account")
    pe.custom_lease_agreement = lease.name
    pe.reference_no = lease.name
    pe.reference_date = today

    # Append references properly
    for ref in references:
        pe.append("references", ref)

    pe.insert(ignore_permissions=True)
    pe.submit()

    return {
        "message": "Payment processed successfully.",
        "payment_entry": pe.name,
        "invoices_paid": [r["reference_name"] for r in references],
        "excess_amount": pe.unallocated_amount,
        "created_invoices": created_invoices
    }
# TO DO : Handle excess payments