# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


class LeaseAgreement(Document):
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
        for row in self.chargable_services:
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

