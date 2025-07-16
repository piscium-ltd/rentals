# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class Property(Document):
    def after_insert(self):
        company = frappe.db.get_value("Landlord", self.landlord, "company")
        try:
            asset = frappe.get_doc({
                "doctype": "Asset",
                "item_code": "Rental Property",
                "asset_name": self.property_name,
                "asset_category": "Investment Property",
                "company": company,
                "location": self.location,
                "is_existing_asset": 1,
                "available_for_use_date": frappe.utils.today(),
                "gross_purchase_amount": 1,
            })
            asset.insert(ignore_permissions=True)
            asset.submit()
            self.db_set("asset", asset.name)
            frappe.msgprint(f"✅ Asset <b>{asset.name}</b> created successfully.")
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Property.after_insert: Asset creation failed for {self.name}")
