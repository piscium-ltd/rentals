# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
import random
import re
from frappe import _
from frappe.model.document import Document

class Landlord(Document):
    def validate(self):
        if self.kra_pin:
            kra_pin = self.kra_pin.strip().upper()
            if not re.fullmatch(r"[AP]\d{9}[A-Z]", kra_pin):
                frappe.throw(_("❌ Invalid KRA PIN format. Use format like <b>A123456789B</b> or <b>P051234567K</b>."))
            self.kra_pin = kra_pin

    def after_insert(self):
        # Set abbreviation
        abbr = self.get_abbreviation()
        self.db_set("abbr", abbr)

        # Set company name based on landlord type
        company_name = self.company_name if self.landlord_type == "Company" else abbr

        # Create company if it doesn't exist
        if not frappe.db.exists("Company", {"company_name": company_name}):
            self.create_company(company_name, abbr)

        self.db_set("company", company_name)

        # Create user if it doesn't exist
        if self.email and not frappe.db.exists("User", self.email):
            self.create_user(company_name if self.landlord_type == "Company" else self.full_name)

    def create_company(self, company_name, abbr):
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

        frappe.msgprint(_("✅ Company <b>{0}</b> created successfully.").format(company_name))

    def create_user(self, name):
        user = frappe.get_doc({
            "doctype": "User",
            "email": self.email,
            "first_name": name,
            "send_welcome_email": 0,
            "role_profiles": [
                {
                    "role_profile": "Rentals"
                }
            ]
        })
        user.insert(ignore_permissions=True)

        self.db_set("user", user.name)

        # Permission to view their own Landlord record
        frappe.get_doc({
            "doctype": "User Permission",
            "user": user.name,
            "allow": "Landlord",
            "for_value": self.name,
        }).insert(ignore_permissions=True)

        # Additional permission to view their associated Company
        frappe.get_doc({
            "doctype": "User Permission",
            "user": user.name,
            "allow": "Company",
            "for_value": self.company,
        }).insert(ignore_permissions=True)

        frappe.msgprint(_("✅ User <b>{0}</b> created successfully.").format(user.name))

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

        frappe.throw(_("❌ Unable to generate a unique abbreviation after {0} attempts.").format(max_attempts))
