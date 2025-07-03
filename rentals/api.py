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

    # Handle Sales Order (Onboarding Payment)
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
                    "so_detail": frappe.db.get_value("Sales Order Item", {
                        "parent": so_doc.name, "item_code": row.service
                    }, "name")
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
                    "due_date": today,
                    "posting_date": today,
                    "debit_to": frappe.get_value("Company", company, "default_receivable_account"),
                    "currency": currency,
                    "selling_price_list": price_list,
                    "custom_lease_agreement": lease.name,
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
                    "due_date": today,
                    "posting_date": today,
                    "debit_to": frappe.get_value("Company", company, "default_receivable_account"),
                    "currency": currency,
                    "selling_price_list": price_list,
                    "custom_lease_agreement": lease.name,
                    "items": recurring_items,
                    "remarks": "Initial recurring services invoice"
                })
                invoice2.insert()
                invoice2.submit()
                created_invoices.append(invoice2.name)

    # Pay outstanding invoices for this lease
    invoices = frappe.get_all(
        "Sales Invoice",
        filters={
            "customer": customer,
            "custom_lease_agreement": lease.name,
            "outstanding_amount": [">", 0],
            "docstatus": 1
        }, 
        fields=["name", "outstanding_amount"],
        order_by="posting_date asc"
    )

    remaining_amount = amount
    references = []

    for inv in invoices:
        if remaining_amount <= 0:
            break
        to_allocate = min(inv.outstanding_amount, remaining_amount)
        references.append({
            "reference_doctype": "Sales Invoice",
            "reference_name": inv.name,
            "total_amount": inv.outstanding_amount,
            "outstanding_amount": inv.outstanding_amount,
            "allocated_amount": to_allocate
        })
        remaining_amount -= to_allocate

    # Step 3: Create Payment Entry
    payment_entry = frappe.new_doc("Payment Entry")
    payment_entry.payment_type = "Receive"
    payment_entry.party_type = "Customer"
    payment_entry.party = customer
    payment_entry.posting_date = today
    payment_entry.paid_from = frappe.get_value("Company", company, "default_receivable_account")
    payment_entry.paid_to = frappe.get_value("Company", company, "default_bank_account")
    payment_entry.received_amount = amount
    payment_entry.paid_amount = amount
    payment_entry.unallocated_amount = remaining_amount if remaining_amount > 0 else 0
    payment_entry.company = company
    payment_entry.custom_lease_agreement = lease.name
    payment_entry.reference_no = lease.name
    payment_entry.reference_date = today

    for ref in references:
        payment_entry.append("references", ref)

    payment_entry.insert()
    payment_entry.submit()

    return {
        "message": "Payment processed successfully.",
        "payment_entry": payment_entry.name,
        "invoices_paid": [r["reference_name"] for r in references],
        "excess_amount": payment_entry.unallocated_amount,
        "created_invoices": created_invoices
    }
