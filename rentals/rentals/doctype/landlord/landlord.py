# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class Landlord(Document):
    def after_insert(self):
        # Determine the company name based on landlord type
        company_name = self.company_name if self.landlord_type == "Company" else self.full_name

        if not company_name:
            frappe.throw("Company Name or Full Name is required to create a Company.")

        # Generate a unique abbreviation
        abbr = self.get_abbreviation(company_name)
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

    def get_abbreviation(self, name):
        """Generate a unique uppercase abbreviation from the first letters of each word."""
        base_abbr = "".join(word[0].upper() for word in name.strip().split() if word)
        candidate = base_abbr
        count = 1

        while frappe.db.exists("Company", {"abbr": candidate}):
            candidate = f"{base_abbr}{count}"
            count += 1

        return candidate
