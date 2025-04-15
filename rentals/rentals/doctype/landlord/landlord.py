# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class Landlord(Document):
    def after_insert(self):
        if not self.supplier:
            # Check if a supplier with this name already exists
            existing = frappe.db.exists("Supplier", {"supplier_name": self.full_name})
            if not existing:
                supplier = frappe.get_doc({
                    "doctype": "Supplier",
                    "supplier_name": self.full_name,
                    "supplier_type": "Individual",
                    "email_id": self.email or "",
                    "tax_id": self.kra_pin or ""
                })
                supplier.insert(ignore_permissions=True)
                self.supplier = supplier.name
                self.db_update()
                frappe.msgprint(f"✅ A new Supplier <b>{self.supplier}</b> has been created.")
