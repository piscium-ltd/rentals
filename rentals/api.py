import frappe
from frappe.utils import getdate, nowdate

@frappe.whitelist(allow_guest=True)
def payment_validation():
    """M-Pesa C2B Validation URL handler."""
    try:
        data = frappe.local.form_dict
        account_number = data.get("BillRefNumber")

        if frappe.db.exists("Lease Agreement", account_number):
            return {"ResultCode": 0, "ResultDesc": "Accepted"}
        return {"ResultCode": "C2B00012", "ResultDesc": "Invalid Account Number"}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "M-Pesa C2B Validation Error")
        return {"ResultCode": "C2B00016", "ResultDesc": f"Validation error: {str(e)}"}

@frappe.whitelist(allow_guest=True)
def payment_confirmation():
    """M-Pesa C2B Confirmation URL handler."""
    try:
        data = frappe.local.form_dict
        account_number = data.get("BillRefNumber")
        amount = data.get("TransAmount")
        mpesa_receipt = data.get("TransID")
        phone_number = data.get("MSISDN")

        if not account_number:
            return {"ResultCode": "C2B00012", "ResultDesc": "Invalid Account Number"}
        if not amount:
            return {"ResultCode": "C2B00013", "ResultDesc": "Invalid Amount"}

        # Process the payment
        result = payment_webhook(account_number, amount)

        # Attach metadata to Payment Entry
        if result.get("payment_entry"):
            frappe.db.set_value("Payment Entry", result["payment_entry"], {
                "reference_no": mpesa_receipt,
                "reference_date": getdate(nowdate()),
                "remarks": f"M-Pesa payment from {phone_number}"
            })

        return {"ResultCode": 0, "ResultDesc": "Confirmation received successfully"}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "M-Pesa C2B Confirmation Error")
        return {"ResultCode": "C2B00016", "ResultDesc": f"Processing error: {str(e)}"}

def payment_webhook(account_number, amount):
    """Core webhook that processes payments for a Lease Agreement."""
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

        # Handle Sales Order invoices
        sales_order = frappe.db.get_value("Sales Order", {"custom_lease_agreement": lease.name}, "name")
        if sales_order:
            created_invoices += handle_sales_order_invoices(
                lease, sales_order, customer, company, currency, price_list
            )

            # Handle Full Agency invoices
            if lease.agency_type == "Full Agency":
                created_invoices += handle_full_agency_invoices(lease, currency)

        # Allocate payment to invoices
        references, unallocated = allocate_payment_to_invoices(lease, customer, amount)

        # Create Payment Entry
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
        frappe.log_error(frappe.get_traceback(), "Payment Webhook Error")
        frappe.throw(f"Error while processing payment: {str(e)}")

def handle_sales_order_invoices(lease, sales_order, customer, company, currency, price_list):
    """Generate invoices (deposit + recurring) from Sales Order linked to Lease."""
    try:
        so_doc = frappe.get_doc("Sales Order", sales_order)
        if so_doc.per_billed >= 100:
            return []

        deposit_items, recurring_items, created = [], [], []

        # Security deposits
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

        # Rent
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

        # Chargeable services
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
        frappe.log_error(frappe.get_traceback(), "Sales Invoice Creation Error")
        return []

def handle_full_agency_invoices(lease, currency):
    """Create sales & purchase invoices for 'Full Agency' leases."""
    try:
        landlord_company = frappe.db.get_value("Landlord", lease.landlord, "company")
        agent_company = frappe.db.get_value("Agent", lease.agent, "company")
        agent_customer = frappe.db.get_value("Agent", lease.agent, "customer")
        landlord_supplier = frappe.db.get_value("Landlord", lease.landlord, "supplier")
        agent_price_list = frappe.db.get_value("Customer", agent_customer, "default_price_list")

        if not all([landlord_company, agent_company, agent_customer, landlord_supplier, agent_price_list]):
            return []

        if not lease.rent_item or not lease.base_rental_amount:
            return []

        rent_item = [{
            "item_code": lease.rent_item,
            "qty": 1,
            "rate": lease.base_rental_amount,
            "description": "Rent"
        }]

        return [
            create_sales_invoice(
                agent_customer, landlord_company, lease, rent_item,
                currency, agent_price_list, "Rent invoice to Agent"
            ),
            create_purchase_invoice(
                landlord_supplier, agent_company, lease, rent_item,
                currency, agent_price_list, "Rent invoice from Landlord"
            )
        ]

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Full Agency Invoice Error")
        return []

def create_sales_invoice(customer, company, lease, items, currency, price_list, remarks):
    """Create and submit a Sales Invoice."""
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
    invoice.insert(ignore_permissions=True)
    invoice.submit()
    return invoice.name

def create_purchase_invoice(supplier, company, lease, items, currency, price_list, remarks):
    """Create and submit a Purchase Invoice."""
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
    invoice.insert(ignore_permissions=True)
    invoice.submit()
    return invoice.name

def allocate_payment_to_invoices(lease, customer, amount):
    """Allocate received payment to outstanding invoices."""
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

    remaining, references = amount, []
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
    """Create and submit a Payment Entry for received M-Pesa payment."""
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
    payment_entry.insert(ignore_permissions=True)
    payment_entry.submit()
    return payment_entry
