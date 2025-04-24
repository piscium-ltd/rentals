# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import today, add_days, add_months, add_years, getdate
from erpnext.accounts.doctype.payment_request.payment_request import make_payment_request


class LeaseAgreement(Document):
    def before_save(self):
        # Calculate Grand Total from child table
        total = 0
        base_date = getdate(today())

        for row in self.chargeable_services:
            total += row.rate

            # Only set billing date if not already set
            if not row.billing_date:
                if row.billing_cycle == "Once":
                    row.billing_date = base_date
                elif row.billing_cycle == "Daily":
                    row.billing_date = add_days(base_date, 1)
                elif row.billing_cycle == "Weekly":
                    row.billing_date = add_days(base_date, 7)
                elif row.billing_cycle == "Monthly":
                    row.billing_date = add_months(base_date, 1)
                elif row.billing_cycle == "Annually":
                    row.billing_date = add_years(base_date, 1)
                else:
                    row.billing_date = base_date

        self.grand_total = total

    def on_submit(self):
        customer_name = self.tenant_name
        price_list_name = f"{customer_name} Price List"

        # 1. Create the price list if it doesn't exist
        if not frappe.db.exists("Price List", price_list_name):
            price_list = frappe.get_doc({
                "doctype": "Price List",
                "price_list_name": price_list_name,
                "currency": self.billing_currency,
                "selling": 1,
                "enabled": 1
            })
            price_list.insert(ignore_permissions=True)
            frappe.msgprint(_(f"✅ Created new Price List: {price_list_name}"))

        # 2. Link to customer's default price list
        tenant_doc = frappe.get_doc("Tenant", self.tenant)
        if tenant_doc.customer:
            customer_doc = frappe.get_doc("Customer", tenant_doc.customer)
            customer_doc.default_currency = self.billing_currency
            if customer_doc.default_price_list != price_list_name:
                customer_doc.default_price_list = price_list_name
                customer_doc.save(ignore_permissions=True)
                frappe.msgprint(_(f"✅ Updated default Price List for Customer: {customer_doc.name}"))
        else:
            frappe.msgprint(_("⚠️ Tenant is not linked to a Customer."), alert=True)
            return

        # 3. Add or update item prices for chargeable services
        for row in self.chargeable_services:
            item_code = row.service
            rate = row.rate

            if not rate:
                frappe.msgprint(_(f"⚠️ No rate found for item {item_code}. Skipping."))
                continue

            item_price_name = frappe.db.exists("Item Price", {
                "item_code": item_code,
                "price_list": price_list_name
            })

            if item_price_name:
                item_price = frappe.get_doc("Item Price", item_price_name)
                item_price.price_list_rate = rate
                item_price.save(ignore_permissions=True)
                frappe.msgprint(_(f"🔁 Updated price for item {item_code} in {price_list_name}"))
            else:
                item_price = frappe.get_doc({
                    "doctype": "Item Price",
                    "item_code": item_code,
                    "price_list": price_list_name,
                    "price_list_rate": rate,
                    "currency": self.billing_currency,
                    "customer": customer_name
                })
                item_price.insert(ignore_permissions=True)
                frappe.msgprint(_(f"✅ Created new price for item {item_code} in {price_list_name}"))

        # 4. Create Sales Order and Payment Request
        try:
            sales_order = frappe.get_doc({
                "doctype": "Sales Order",
                "customer": tenant_doc.customer,
                "currency": self.billing_currency,
                "selling_price_list": price_list_name,
                "transaction_date": frappe.utils.nowdate(),
                "delivery_date": frappe.utils.nowdate(),
                "items": [
                    {
                        "item_code": row.service,
                        "qty": 1,
                        "rate": row.rate,
                        "delivery_date": frappe.utils.nowdate()
                    }
                    for row in self.chargeable_services
                ]
            })
            sales_order.insert(ignore_permissions=True)
            sales_order.submit()
            self.sales_order_reference = sales_order.name
            self.save(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "LeaseAgreement: Sales Order Error")

        try:
            recipient_email = tenant_doc.email
            if not recipient_email:
                frappe.msgprint(_("⚠️ Tenant does not have an email. Skipping Payment Request creation."))
                return

            payment_request = make_payment_request(
                dt="Sales Order",
                dn=sales_order.name,
                recipient_id=recipient_email,
                submit_doc=True
            )
            self.payment_request_reference = payment_request.name
            self.save(ignore_permissions=True)
            frappe.msgprint(_(f"✅ Created new Payment Request: {payment_request.name}"))

        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "LeaseAgreement: Payment Request Error")
            frappe.throw(_("❌ Could not create Payment Request."))

    def on_cancel(self):
        try:
            # 1. Cancel or Delete the Payment Request
            if self.payment_request_reference:
                payment_request = frappe.get_doc("Payment Request", self.payment_request_reference)

                if payment_request.docstatus == 0:
                    payment_request.delete()
                    frappe.msgprint(_(f"✅ Deleted Payment Request: {self.payment_request_reference}"))

                elif payment_request.docstatus == 1:
                    payment_request.cancel()
                    frappe.msgprint(_(f"✅ Canceled Payment Request: {self.payment_request_reference}"))
                frappe.db.set_value(self.doctype, self.name, "payment_request_reference", "")

            # 2. Cancel the Sales Order
            if self.sales_order_reference:
                sales_order = frappe.get_doc("Sales Order", self.sales_order_reference)

                if sales_order.docstatus == 1:
                    sales_order.cancel()
                frappe.db.set_value(self.doctype, self.name, "sales_order_reference", "")

        except Exception:
            frappe.log_error(frappe.get_traceback(), "LeaseAgreement: Error while cancelling Payment Request or Sales Order")
            frappe.msgprint(_("⚠️ An error occurred during cancellation. Please check the error log."))
