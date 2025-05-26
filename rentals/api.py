import frappe

DEPOSIT_ITEM_CODE = "Deposit"

@frappe.whitelist(allow_guest=True)
def register_payment(**kwargs):
    data = frappe.form_dict
    account_number = data.get("account_number")

    if not account_number:
        return {"error": "Missing account_number in request"}

    doctype = get_doctype_from_account_number(account_number)
    if not doctype:
        return {"error": "Unknown document type for account_number"}

    try:
        doc = frappe.get_doc(doctype, account_number)

        if doctype == "Sales Invoice":
            return handle_sales_invoice(doc)

        if doctype == "Sales Order":
            return handle_sales_order(doc)

    except frappe.DoesNotExistError:
        return {"error": f"{doctype} with ID {account_number} not found"}
    except Exception as e:
        return {"error": str(e)}


def get_doctype_from_account_number(account_number):
    if account_number.startswith("SAL-ORD"):
        return "Sales Order"
    if account_number.startswith("ACC-SINV"):
        return "Sales Invoice"
    return None


def create_payment_entry(party, company, invoice):
    return frappe.get_doc({
        "doctype": "Payment Entry",
        "payment_type": "Receive",
        "party_type": "Customer",
        "party": party,
        "posting_date": frappe.utils.nowdate(),
        "paid_from": frappe.get_value("Company", company, "default_receivable_account"),
        "paid_to": frappe.get_value("Company", company, "default_bank_account"),
        "received_amount": invoice.outstanding_amount,
        "paid_amount": invoice.outstanding_amount,
        "references": [{
            "reference_doctype": "Sales Invoice",
            "reference_name": invoice.name,
            "total_amount": invoice.grand_total,
            "outstanding_amount": invoice.outstanding_amount,
            "allocated_amount": invoice.outstanding_amount,
        }],
        "company": company,
        "reference_no": invoice.name,
        "reference_date": frappe.utils.nowdate(),
    })


def handle_sales_invoice(doc):
    payment_entry = create_payment_entry(doc.customer, doc.company, doc)
    payment_entry.insert()
    payment_entry.submit()

    return {
        "sales_invoice": doc.name,
        "payment_entry": payment_entry.name
    }


def handle_sales_order(doc):
    deposit_item = next((item for item in doc.items if item.item_code == DEPOSIT_ITEM_CODE), None)
    other_items = [item for item in doc.items if item.item_code != DEPOSIT_ITEM_CODE]

    if not deposit_item:
        return {"error": "No Deposit item found in Sales Order"}

    # Create Deposit Certificate
    deposit_certificate = frappe.get_doc({
        "doctype": "Deposit Certificate",
        "tenant": doc.customer,
        "sales_order": doc.name,
        "deposit_amount": deposit_item.amount,
        "date": frappe.utils.nowdate()
    })
    deposit_certificate.insert()
    deposit_certificate.submit()

    # Create Sales Invoice
    sales_invoice = frappe.new_doc("Sales Invoice")
    sales_invoice.update({
        "customer": doc.customer,
        "due_date": frappe.utils.nowdate(),
        "posting_date": frappe.utils.nowdate(),
        "company": doc.company,
        "debit_to": frappe.get_value("Company", doc.company, "default_receivable_account")
    })

    for item in other_items:
        sales_invoice.append("items", {
            "item_code": item.item_code,
            "item_name": item.item_name,
            "qty": item.qty,
            "rate": item.rate,
            "uom": item.uom,
            "warehouse": item.warehouse,
            "cost_center": item.cost_center
        })

    sales_invoice.insert()
    sales_invoice.submit()

    # Create Payment Entry
    payment_entry = create_payment_entry(sales_invoice.customer, sales_invoice.company, sales_invoice)
    payment_entry.insert()
    payment_entry.submit()

    return {
        "sales_order": doc.name,
        "deposit_certificate": deposit_certificate.name,
        "sales_invoice": sales_invoice.name,
        "payment_entry": payment_entry.name
    }
