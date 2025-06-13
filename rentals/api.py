import frappe

DEPOSIT_CYCLE = "Once"

@frappe.whitelist(allow_guest=True)
def register_payment(**kwargs):
    data = frappe.form_dict
    lease_agreement_id = data.get("account_number")
    amount_paid = float(data.get("amount", 0))

    if not lease_agreement_id or not amount_paid:
        return {"error": "Missing lease_agreement_id or amount"}

    try:
        lease_agreement = frappe.get_doc("Lease Agreement", lease_agreement_id)
    except frappe.DoesNotExistError:
        return {"error": f"Lease Agreement {lease_agreement_id} not found"}

    # Check if a Payment Entry already exists
    existing_payment = frappe.db.exists("Payment Entry", {
        "custom_lease_agreement": lease_agreement_id
    })

    if existing_payment:
        return handle_invoice_payment(lease_agreement, amount_paid)
    else:
        return handle_sales_order_payment(lease_agreement, amount_paid)


def handle_invoice_payment(lease_agreement, amount_paid):
    invoices = frappe.get_all("Sales Invoice",
        filters={
            "custom_lease_agreement": lease_agreement.name,
            "docstatus": 1,
            "outstanding_amount": (">", 0)
        },
        fields=["name", "grand_total", "outstanding_amount", "customer", "company", "posting_date"],
        order_by="posting_date asc"
    )

    if not invoices:
        return {"error": "No unpaid Sales Invoices found for this Lease Agreement"}

    total_allocated = 0
    payment_references = []

    for inv in invoices:
        if total_allocated >= amount_paid:
            break

        allocatable = min(inv.outstanding_amount, amount_paid - total_allocated)

        payment_references.append({
            "reference_doctype": "Sales Invoice",
            "reference_name": inv.name,
            "total_amount": inv.grand_total,
            "outstanding_amount": inv.outstanding_amount,
            "allocated_amount": allocatable,
        })

        total_allocated += allocatable

    if not payment_references:
        return {"error": "No payment could be allocated"}

    payment_entry = frappe.get_doc({
        "doctype": "Payment Entry",
        "payment_type": "Receive",
        "party_type": "Customer",
        "party": invoices[0].customer,
        "posting_date": frappe.utils.nowdate(),
        "paid_from": frappe.get_value("Company", invoices[0].company, "default_receivable_account"),
        "paid_to": frappe.get_value("Company", invoices[0].company, "default_bank_account"),
        "received_amount": total_allocated,
        "paid_amount": total_allocated,
        "company": invoices[0].company,
        "custom_lease_agreement": lease_agreement.name,
        "reference_no": lease_agreement.name,
        "reference_date": frappe.utils.nowdate(),
        "references": payment_references
    })

    payment_entry.insert()
    payment_entry.submit()

    return {
        "lease_agreement": lease_agreement.name,
        "payment_entry": payment_entry.name,
        "invoices_paid": [ref["reference_name"] for ref in payment_references],
        "total_allocated": total_allocated,
        "remaining_unallocated": amount_paid - total_allocated
    }


def handle_sales_order_payment(lease_agreement, amount_paid):
    sales_order_name = frappe.db.get_value("Sales Order", {
        "custom_lease_agreement": lease_agreement.name
    })

    if not sales_order_name:
        return {"error": "No Sales Order found for this Lease Agreement"}

    sales_order = frappe.get_doc("Sales Order", sales_order_name)

    payment_entry = create_payment_entry(
        sales_order.customer,
        sales_order.company,
        sales_order,
        lease_agreement.name,
        amount_paid
    )
    payment_entry.insert()
    payment_entry.submit()

    deposit_services = []
    regular_services = []

    for cs in lease_agreement.chargeable_services:
        item = {
            "item_code": cs.item,
            "item_name": cs.item_name,
            "qty": cs.qty,
            "rate": cs.rate,
            "uom": cs.uom,
            "warehouse": cs.warehouse,
            "cost_center": cs.cost_center,
            "sales_order": sales_order.name
        }
        if cs.billing_cycle == DEPOSIT_CYCLE:
            deposit_services.append(item)
        else:
            regular_services.append(item)

    created_docs = {
        "payment_entry": payment_entry.name,
        "sales_order": sales_order.name,
        "lease_agreement": lease_agreement.name
    }

    if deposit_services:
        deposit_invoice = create_sales_invoice(
            lease_agreement, deposit_services, sales_order.customer, sales_order.company, sales_order.name
        )
        created_docs["deposit_certificate"] = deposit_invoice.name

    if regular_services:
        sales_invoice = create_sales_invoice(
            lease_agreement, regular_services, sales_order.customer, sales_order.company, sales_order.name
        )
        created_docs["sales_invoice"] = sales_invoice.name

    return created_docs


def create_sales_invoice(lease_agreement, items, customer, company, sales_order_name):
    invoice = frappe.new_doc("Sales Invoice")
    invoice.update({
        "customer": customer,
        "company": company,
        "custom_lease_agreement": lease_agreement.name,
        "posting_date": frappe.utils.nowdate(),
        "due_date": frappe.utils.nowdate(),
        "debit_to": frappe.get_value("Company", company, "default_receivable_account"),
        "allocate_advances_automatically": 1
    })

    for item in items:
        item.update({
            "sales_order": sales_order_name
        })
        invoice.append("items", item)

    invoice.insert()
    invoice.submit()
    return invoice


def create_payment_entry(party, company, reference_doc, lease_agreement_id, amount):
    return frappe.get_doc({
        "doctype": "Payment Entry",
        "payment_type": "Receive",
        "party_type": "Customer",
        "party": party,
        "posting_date": frappe.utils.nowdate(),
        "paid_from": frappe.get_value("Company", company, "default_receivable_account"),
        "paid_to": frappe.get_value("Company", company, "default_bank_account"),
        "received_amount": amount,
        "paid_amount": amount,
        "company": company,
        "reference_no": reference_doc.name,
        "reference_date": frappe.utils.nowdate(),
        "custom_lease_agreement": lease_agreement_id,
        "references": [{
            "reference_doctype": reference_doc.doctype,
            "reference_name": reference_doc.name,
            "total_amount": reference_doc.grand_total,
            "outstanding_amount": reference_doc.outstanding_amount,
            "allocated_amount": amount,
        }]
    })
