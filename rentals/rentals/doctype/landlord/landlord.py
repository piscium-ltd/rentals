# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
import random
from frappe import _

class Landlord(Document):
    def after_insert(self):
        # Generate and set a unique abbreviation
        abbr = self.get_abbreviation()
        self.db_set("abbr", abbr)

        # Determine the company name based on landlord type
        company_name = self.company_name if self.landlord_type == "Company" else abbr

        # Check if the company already exists
        if not frappe.db.exists("Company", {"company_name": company_name}):
            default_company = frappe.db.get_single_value("Global Defaults", "default_company")

            # Create the new company
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

            frappe.msgprint(_("✅ Company <b>{0}</b> created successfully.").format(company_name))

        # Link the landlord to the created or existing company
        self.db_set("company", company_name)

    def get_abbreviation(self):
        safe_charset = "ACDEFHJKMNPRTVWXY"
        blacklist = {"FAP", "FAT", "WET", "WTF"}
        max_attempts = 5000

        for _ in range(max_attempts):
            abbr = ''.join(random.choices(safe_charset, k=3))

            if abbr in blacklist:
                continue

            if not frappe.db.exists("Company", {"abbr": abbr}):
                return abbr

        frappe.throw(_("Unable to generate a unique abbreviation after many attempts."))
