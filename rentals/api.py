import frappe
from frappe.utils import getdate, nowdate

@frappe.whitelist(allow_guest=True)
def bank_payment_webhook(account_number, amount):
    """
    Webhook to process incoming bank payments for a lease agreement.

    Creates sales and purchase invoices if needed and allocates the payment 
    to outstanding invoices related to the lease agreement.
    """
    try:
        amount = float(amount)
        posting_date = getdate(nowdate())

        lease = frappe.get_doc("Lease Agreement", account_number)
        customer, company = lease.customer, lease.company

        if not customer or not company:
            frappe.throw("Customer or Company not found for this lease.")

        price_list = frappe.db.get_value("Customer", customer, "default_price_list")
        currency = lease.billing_currency
        created_invoices = []

        # Check if a sales order exists and generate relevant invoices
        sales_order = frappe.db.get_value("Sales Order", {"custom_lease_agreement": lease.name}, "name")
        if sales_order:
            created_invoices += handle_sales_order_invoices(
                lease, sales_order, customer, company, currency, price_list
            )

            # Handle Full Agency invoices
            if lease.agency_type == "Full Agency":
                created_invoices += handle_full_agency_invoices(lease, currency)

        # Allocate payment to outstanding invoices
        references, unallocated = allocate_payment_to_invoices(lease, customer, amount)

        # Create the payment entry
        payment_entry = create_payment_entry(
            lease, customer, company, amount, unallocated, references, posting_date
        )

        return {
            "message": "Payment processed successfully.",
            "payment_entry": payment_entry.name,
            "invoices_paid": [r["reference_name"] for r in references],
            "excess_amount": unallocated,
            "created_invoices": created_invoices
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Bank Payment Webhook Error")
        frappe.throw(f"An error occurred while processing the payment: {str(e)}")

def handle_sales_order_invoices(lease, sales_order, customer, company, currency, price_list):
    """
    Generate Sales Invoices for deposit and recurring services from a Sales Order.
    """
    try:
        so_doc = frappe.get_doc("Sales Order", sales_order)
        if so_doc.per_billed >= 100:
            return []

        # Prepare security deposits for deposit certificate
        deposit_items = []
        for row in lease.security_deposits:
            so_detail = frappe.db.get_value(
                "Sales Order Item",
                {"parent": so_doc.name, "item_code": row.security_type},
                "name"
            )
            if so_detail:
                deposit_items.append({
                    "item_code": row.security_type,
                    "qty": 1,
                    "rate": row.rate,
                    "description": "Security Deposit",
                    "sales_order": so_doc.name,
                    "so_detail": so_detail
                })

        # Prepare rent + chargeable services for recurring invoice
        recurring_items = []

        # Add rent item
        if lease.rent_item and lease.base_rental_amount:
            so_detail = frappe.db.get_value(
                "Sales Order Item",
                {"parent": so_doc.name, "item_code": lease.rent_item},
                "name"
            )
            if so_detail:
                recurring_items.append({
                    "item_code": lease.rent_item,
                    "qty": 1,
                    "rate": lease.base_rental_amount,
                    "description": "Base Rent",
                    "sales_order": so_doc.name,
                    "so_detail": so_detail
                })

        # Add chargeable services
        for row in lease.chargeable_services:
            so_detail = frappe.db.get_value(
                "Sales Order Item",
                {"parent": so_doc.name, "item_code": row.service},
                "name"
            )
            if so_detail:
                recurring_items.append({
                    "item_code": row.service,
                    "qty": 1,
                    "rate": row.rate,
                    "description": row.billing_cycle,
                    "sales_order": so_doc.name,
                    "so_detail": so_detail
                })

        created = []

        if deposit_items:
            created.append(create_sales_invoice(
                customer, company, lease, deposit_items,
                currency, price_list,
                "Deposit Certificate for onboarding"
            ))

        if recurring_items:
            created.append(create_sales_invoice(
                customer, company, lease, recurring_items,
                currency, price_list,
                "Initial recurring services invoice"
            ))

        return created

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Sales Order Invoice Creation Error")
        frappe.msgprint("Error creating sales order invoices.")
        return []

def handle_full_agency_invoices(lease, currency):
    """
    Creates sales and purchase invoices for rent item if agency type is 'Full Agency'.
    """
    try:
        landlord_company = frappe.db.get_value("Landlord", lease.landlord, "company")
        agent_company = frappe.db.get_value("Agent", lease.agent, "company")
        agent_customer = frappe.db.get_value("Agent", lease.agent, "customer")
        landlord_supplier = frappe.db.get_value("Landlord", lease.landlord, "supplier")
        agent_price_list = frappe.db.get_value("Customer", agent_customer, "default_price_list")

        if not all([landlord_company, agent_company, agent_customer, landlord_supplier, agent_price_list]):
            frappe.msgprint("Missing linked company, customer, supplier or price list.")
            return []

        if not lease.rent_item or not lease.base_rental_amount:
            frappe.msgprint("Missing rent item or base rental amount.")
            return []

        rent_item = [{
            "item_code": lease.rent_item,
            "qty": 1,
            "rate": lease.base_rental_amount,
            "description": "Rent"
        }]

        created = []
        created.append(create_sales_invoice(
            agent_customer,
            landlord_company,
            lease,
            rent_item,
            currency,
            agent_price_list,
            "Rent invoice to Agent"
        ))
        created.append(create_purchase_invoice(
            landlord_supplier,
            agent_company,
            lease,
            rent_item,
            currency,
            agent_price_list,
            "Rent invoice from Landlord"
        ))

        return created

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Full Agency Invoice Error")
        frappe.msgprint("Failed to create full agency invoices.")
        return []

def create_sales_invoice(customer, company, lease, items, currency, price_list, remarks):
    """
    Creates and submits a sales invoice.
    """
    invoice = frappe.get_doc({
        "doctype": "Sales Invoice",
        "customer": customer,
        "company": company,
        "due_date": lease.start_date,
        "set_posting_time": 1,
        "posting_date": lease.start_date,
        "debit_to": frappe.get_value("Company", company, "default_receivable_account"),
        "currency": currency,
        "selling_price_list": price_list,
        "custom_lease_agreement": lease.name,
        "items": items,
        "remarks": remarks
    })
    invoice.insert()
    invoice.submit()
    return invoice.name

def create_purchase_invoice(supplier, company, lease, items, currency, price_list, remarks):
    """
    Creates and submits a purchase invoice.
    """
    invoice = frappe.get_doc({
        "doctype": "Purchase Invoice",
        "supplier": supplier,
        "company": company,
        "due_date": lease.start_date,
        "set_posting_time": 1,
        "posting_date": lease.start_date,
        "credit_to": frappe.get_value("Company", company, "default_payable_account"),
        "currency": currency,
        "buying_price_list": price_list,
        "custom_lease_agreement": lease.name,
        "items": items,
        "remarks": remarks
    })
    invoice.insert()
    invoice.submit()
    return invoice.name

def allocate_payment_to_invoices(lease, customer, amount):
    """
    Allocates the given amount to outstanding sales invoices related to the lease.
    Returns list of payment references and unallocated amount.
    """
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

    remaining = amount
    references = []

    for inv in invoices:
        if remaining <= 0:
            break

        to_allocate = min(inv.outstanding_amount, remaining)
        references.append({
            "reference_doctype": "Sales Invoice",
            "reference_name": inv.name,
            "total_amount": inv.outstanding_amount,
            "outstanding_amount": inv.outstanding_amount,
            "allocated_amount": to_allocate
        })
        remaining -= to_allocate

    return references, remaining

def create_payment_entry(lease, customer, company, amount, unallocated, references, posting_date):
    """
    Creates and submits a Payment Entry to reflect the received amount.
    """
    payment_entry = frappe.new_doc("Payment Entry")
    payment_entry.update({
        "payment_type": "Receive",
        "party_type": "Customer",
        "party": customer,
        "posting_date": posting_date,
        "paid_from": frappe.get_value("Company", company, "default_receivable_account"),
        "paid_to": frappe.get_value("Company", company, "default_bank_account"),
        "received_amount": amount,
        "paid_amount": amount,
        "unallocated_amount": unallocated,
        "company": company,
        "custom_lease_agreement": lease.name,
        "reference_no": lease.name,
        "reference_date": posting_date,
        "references": references
    })
    payment_entry.insert()
    payment_entry.submit()
    return payment_entry
