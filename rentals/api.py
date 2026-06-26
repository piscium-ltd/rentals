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

        send_payment_received_sms(
            account_number=account_number,
            amount=amount,
            mpesa_receipt=mpesa_receipt,
            payer_phone=phone_number,
            payment_entry=result.get("payment_entry"),
        )

        return {"ResultCode": 0, "ResultDesc": "Confirmation received successfully"}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "M-Pesa C2B Confirmation Error")
        return {"ResultCode": "C2B00016", "ResultDesc": f"Processing error: {str(e)}"}

def send_payment_received_sms(account_number, amount, mpesa_receipt=None, payer_phone=None, payment_entry=None):
    """Queue tenant payment SMS without blocking the M-Pesa confirmation callback."""
    try:
        from rentals.sms.transactional import send_payment_received_sms as queue_payment_sms

        queue_payment_sms(
            lease_name=account_number,
            amount=amount,
            mpesa_receipt=mpesa_receipt,
            payer_phone=payer_phone,
            payment_entry=payment_entry,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Payment Received SMS Error")

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
    invoice.flags.ignore_permissions = True
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
    invoice.flags.ignore_permissions = True
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
        "cost_center": frappe.get_value("Company", company, "cost_center"),
        "paid_from_account_currency": frappe.get_value(
            "Account",
            frappe.get_value("Company", company, "default_receivable_account"),
            "account_currency"
        ),
        "paid_to_account_currency": frappe.get_value(
            "Account",
            frappe.get_value("Company", company, "default_bank_account"),
            "account_currency"
        ),
        "party_account_currency": frappe.get_value(
            "Account",
            frappe.get_value("Company", company, "default_receivable_account"),
            "account_currency"
        ),
        "received_amount": amount,
        "paid_amount": amount,
        "unallocated_amount": unallocated,
        "company": company,
        "custom_lease_agreement": lease.name,
        "reference_no": lease.name,
        "reference_date": posting_date,
        "references": references,
        "target_exchange_rate": 1,
        "source_exchange_rate": 1,
    })
    frappe.set_user("Administrator")
    payment_entry.insert()
    payment_entry.submit()
    frappe.set_user("Guest")
    return payment_entry

@frappe.whitelist()
def test_send_sms(phone_number=None, message=None):
    """
    Send a single test SMS through Africa's Talking.

    Request body example:
    {
        "phone_number": "0712345678",
        "message": "Rentals SMS test"
    }
    """
    frappe.only_for("System Manager")

    data = frappe.local.form_dict or {}
    phone_number = phone_number or data.get("phone_number") or data.get("to") or data.get("recipient")
    message = message or data.get("message") or "Rentals SMS test message."

    from rentals.sms.africas_talking import send_sms

    return send_sms(
        recipients=phone_number,
        message=message,
        reference_doctype="Rentals SMS Settings",
        reference_name="Rentals SMS Settings",
        sms_category="Test",
    )

@frappe.whitelist()
def build_sms_campaign_recipients(campaign_name=None):
    """Build recipients for a Rentals SMS Campaign."""
    data = frappe.local.form_dict or {}
    campaign_name = campaign_name or data.get("campaign_name")

    if not campaign_name:
        frappe.throw("Campaign name is required.")

    from rentals.sms.campaign import build_campaign_recipients

    return build_campaign_recipients(campaign_name)


@frappe.whitelist()
def send_sms_campaign(campaign_name=None):
    """Queue a Rentals SMS Campaign for sending."""
    data = frappe.local.form_dict or {}
    campaign_name = campaign_name or data.get("campaign_name")

    if not campaign_name:
        frappe.throw("Campaign name is required.")

    from rentals.sms.campaign import enqueue_campaign_send

    return enqueue_campaign_send(campaign_name)

@frappe.whitelist(allow_guest=True)
def africas_talking_delivery_report(**kwargs):
    """Africa's Talking delivery-report callback wrapper."""
    from rentals.sms.callbacks import africas_talking_delivery_report as process_delivery_report

    return process_delivery_report(**kwargs)

@frappe.whitelist()
def run_sms_reminders(reminder_type=None):
    """
    Manually run automated SMS reminders.

    reminder_type options:
    - All
    - Rent Due
    - Overdue Invoice
    - Lease Expiry
    """
    from rentals.sms.reminders import run_sms_reminders as run_reminders

    data = frappe.local.form_dict or {}
    reminder_type = reminder_type or data.get("reminder_type") or "All"

    return run_reminders(reminder_type=reminder_type)


@frappe.whitelist()
def preview_sms_template(template_name=None, context=None):
    """Preview a Rentals SMS Template with its sample context or supplied JSON context."""
    data = frappe.local.form_dict or {}
    template_name = template_name or data.get("template_name")
    context = context or data.get("context")

    from rentals.sms.templates import preview_sms_template as preview_template

    return preview_template(template_name=template_name, context=context)


@frappe.whitelist(allow_guest=True)
def africas_talking_inbound_sms(**kwargs):
    """Africa's Talking inbound SMS callback wrapper for STOP/START keywords."""
    from rentals.sms.inbound import africas_talking_inbound_sms as process_inbound_sms

    return process_inbound_sms(**kwargs)


@frappe.whitelist()
def preview_sms_cleanup():
    """Preview SMS cleanup impact without changing records."""
    from rentals.sms.cleanup import preview_sms_cleanup as preview_cleanup

    return preview_cleanup()


@frappe.whitelist()
def run_sms_cleanup(dry_run=1, force_delete=0):
    """Run SMS cleanup manually. Defaults to dry-run for safety."""
    data = frappe.local.form_dict or {}
    dry_run = data.get("dry_run", dry_run)
    force_delete = data.get("force_delete", force_delete)

    from rentals.sms.cleanup import run_sms_cleanup as cleanup_logs

    return cleanup_logs(dry_run=dry_run, force_delete=force_delete)
