# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import random

class Landlord(Document):
    def after_insert(self):
        # Determine the company name based on landlord type
        company_name = self.company_name if self.landlord_type == "Company" else self.full_name

        if not company_name:
            frappe.throw("Company Name or Full Name is required to create a Company.")

        # Generate a unique abbreviation
        abbr = self.get_abbreviation()
        self.db_set("abbr", abbr)

        # Create Company if it doesn't exist
        if not frappe.db.exists("Company", {"company_name": company_name}):
            default_company = frappe.db.get_single_value("Global Defaults", "default_company")

            company = frappe.get_doc({
                "doctype": "Company",
                "company_name": company_name,
                "abbr": abbr,
                "default_currency": "KES",
                "country": "Kenya",
                "tax_id": self.kra_pin,
                "create_chart_of_accounts_based_on": "Existing Company",
                "existing_company": default_company
            })
            company.insert(ignore_permissions=True)

        # Link the company to this landlord
        self.db_set("company", company_name)

    def get_abbreviation(self):
        safe_charset = "ACDEFHJKMNPRTVWXY"
        BLACKLIST = {"FAP", "FAT", "WET", "WTF"}
        max_attempts = 5000  # Safety limit to prevent infinite loop

        for _ in range(max_attempts):
            abbr = ''.join(random.choices(safe_charset, k=3))

            if abbr in BLACKLIST:
                continue

            if not frappe.db.exists("Company", {"abbr": abbr}):
                return abbr

        frappe.throw("Unable to generate unique abbreviation after many attempts.")
