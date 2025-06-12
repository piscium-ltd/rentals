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
        base = len(safe_charset)

        # Retrieve current counter from Rental Settings singleton
        counter = frappe.db.get_single_value("Rental Settings", "last_used_counter") or 0

        max_combinations = base ** 3
        if counter >= max_combinations:
            frappe.throw("No more abbreviations available.")

        attempts = 0
        while attempts < max_combinations:
            # Convert counter to base-N abbreviation
            temp = counter
            abbr = ""
            for _ in range(3):
                abbr = safe_charset[temp % base] + abbr
                temp //= base

            # Skip blacklisted words
            if abbr in BLACKLIST:
                counter += 1
                attempts += 1
                continue

            # Check if abbreviation is unique
            if not frappe.db.exists("Company", {"abbr": abbr}):
                # Save updated counter in Rental Settings
                frappe.db.set_value("Rental Settings", None, "last_used_counter", counter + 1)
                return abbr

            counter += 1
            attempts += 1

        frappe.throw("Unable to generate unique abbreviation.")
