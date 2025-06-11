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


def create_payment_entry(party, company, reference_doc):
    reference_doctype = reference_doc.doctype
    reference_name = reference_doc.name

    # Use outstanding_amount if available, otherwise fallback to grand_total (for Sales Order)
    amount = getattr(reference_doc, "outstanding_amount", None)
    if amount is None:
        amount = reference_doc.grand_total

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
        "references": [{
            "reference_doctype": reference_doctype,
            "reference_name": reference_name,
            "total_amount": reference_doc.grand_total,
            "outstanding_amount": amount,
            "allocated_amount": amount,
        }],
        "company": company,
        "reference_no": reference_name,
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
    # Create Payment Entry
    payment_entry = create_payment_entry(doc.customer, doc.company, doc)
    payment_entry.insert()
    payment_entry.submit()

    # Create Deposit Certificate
    deposit_item = next((item for item in doc.items if item.item_code == DEPOSIT_ITEM_CODE), None)

    if not deposit_item:
        return {"error": "No Deposit item found in Sales Order"}

    deposit_certificate = frappe.new_doc("Sales Invoice")
    deposit_certificate.update({
        "customer": doc.customer,
        "company": doc.company,
        "due_date": frappe.utils.nowdate(),
        "posting_date": frappe.utils.nowdate(),
        "debit_to": frappe.get_value("Company", doc.company, "default_receivable_account"),
        "allocate_advances_automatically": 1,
        "items": [{
            "item_code": deposit_item.item_code,
            "item_name": deposit_item.item_name,
            "qty": deposit_item.qty,
            "rate": deposit_item.rate,
            "uom": deposit_item.uom,
            "warehouse": deposit_item.warehouse,
            "cost_center": deposit_item.cost_center,
            "sales_order": doc.name,
            "so_detail": deposit_item.name
        }]
    })
    deposit_certificate.insert()
    deposit_certificate.submit()

    # Create Sales Invoice for remaining items
    other_items = [item for item in doc.items if item.item_code != DEPOSIT_ITEM_CODE]

    if other_items:
        sales_invoice = frappe.new_doc("Sales Invoice")
        sales_invoice.update({
            "customer": doc.customer,
            "company": doc.company,
            "due_date": frappe.utils.nowdate(),
            "posting_date": frappe.utils.nowdate(),
            "debit_to": frappe.get_value("Company", doc.company, "default_receivable_account"),
            "allocate_advances_automatically": 1
        })

        for item in other_items:
            sales_invoice.append("items", {
                "item_code": item.item_code,
                "item_name": item.item_name,
                "qty": item.qty,
                "rate": item.rate,
                "uom": item.uom,
                "warehouse": item.warehouse,
                "cost_center": item.cost_center,
                "sales_order": doc.name,
                "so_detail": item.name,        
            })

        sales_invoice.insert()
        sales_invoice.submit()
    else:
        sales_invoice_name = None

    return {
        "sales_order": doc.name,
        "payment_entry": payment_entry.name,
        "sales_invoice": sales_invoice.name,
        "deposit_certificate": deposit_certificate.name
    }
