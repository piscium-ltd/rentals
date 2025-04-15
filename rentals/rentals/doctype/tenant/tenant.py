# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class Tenant(Document):
    def after_insert(self):
        # Check if customer is already linked
        if not self.customer:
            # Check if a customer with the same name already exists
            existing = frappe.db.exists("Customer", {"customer_name": self.full_name})
            if not existing:
                # Create a new Customer document
                customer = frappe.get_doc({
                    "doctype": "Customer",
                    "customer_name": self.full_name,
                    "customer_type": "Individual",
                    "email_id": self.email or ""
                })
                customer.insert(ignore_permissions=True)
                self.customer = customer.name
                self.db_update()
                frappe.msgprint(f"A new Customer <b>{self.customer}</b> has been created and linked to this Tenant.")
