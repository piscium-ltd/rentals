# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
import random
from frappe.model.document import Document
from frappe import _

class Agent(Document):
    def after_insert(self):
        """After Agent is inserted, generate abbreviation, create company, create user."""
        try:
            abbr = self._get_abbreviation()
            self.db_set("abbr", abbr)

            company_name = abbr

            # Create company if it doesn't exist
            if not frappe.db.exists("Company", {"company_name": company_name}):
                self._create_company(company_name, abbr)

            self.db_set("company", company_name)
            # Create user if email is provided and user doesn't exist
            if self.email and not frappe.db.exists("User", self.email):
                self._create_user(self.full_name)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Agent after_insert Error")
            frappe.throw(_("❌ Failed to set up Agent. Please check error logs."))

    # -------------------------------
    # Private Helper Methods
    # -------------------------------

    def _create_company(self, company_name, abbr):
        """Create a new Company and link it to the agent."""
        try:
            defaults = self._get_global_defaults()

            company = frappe.get_doc({
                "doctype": "Company",
                "company_name": company_name,
                "abbr": abbr,
                "default_currency": defaults.get("default_currency", "KES"),
                "country": defaults.get("country", "Kenya"),
                "create_chart_of_accounts_based_on": "Existing Company",
                "existing_company": defaults.get("default_company")
            })
            company.insert(ignore_permissions=True)

            frappe.msgprint(
                _("✅ Agent created successfully and linked to Company <b>{0}</b>.").format(company_name),
                indicator="green", alert=True
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Company Creation Failed")
            frappe.throw(_("❌ Failed to create associated Company for this Agent."))

    def _create_user(self, name):
        """Create User for Agent and assign permissions."""
        try:
            user = frappe.get_doc({
                "doctype": "User",
                "email": self.email,
                "first_name": name,
                "send_welcome_email": 0,
                "role_profiles": [{"role_profile": "Rentals"}]
            })
            user.insert(ignore_permissions=True)
            self.db_set("user", user.name)

            self._assign_user_permission(user.name, "Agent", self.name)
            self._assign_user_permission(user.name, "Company", self.company)

            frappe.msgprint(_("✅ User <b>{0}</b> created successfully.").format(user.name), indicator="green", alert=True)

        except Exception:
            frappe.log_error(frappe.get_traceback(), "Agent User Creation Failed")
            frappe.throw(_("❌ Failed to create User for this Agent."))

    def _assign_user_permission(self, user, doctype, value):
        """Assign permission to a user for a doctype."""
        try:
            frappe.get_doc({
                "doctype": "User Permission",
                "user": user,
                "allow": doctype,
                "for_value": value,
            }).insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Failed to assign permission for {doctype}")

    def _get_abbreviation(self):
        """Generate a unique 3-letter abbreviation."""
        safe_charset = "ACDEFHJKMNPRTVWXY"
        blacklist = {"FAP", "FAT", "WET", "WTF"}
        max_attempts = 5000

        try:
            for _ in range(max_attempts):
                abbr = ''.join(random.choices(safe_charset, k=3))
                if abbr not in blacklist and not frappe.db.exists("Company", {"abbr": abbr}):
                    return abbr
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Abbreviation Generation Failed")

        frappe.throw(_("❌ Unable to generate a unique abbreviation after {0} attempts.").format(max_attempts))

    def _get_global_defaults(self):
        """Fetch global defaults like company, currency, country."""
        try:
            return {
                "default_company": frappe.db.get_single_value("Global Defaults", "default_company"),
                "default_currency": frappe.db.get_single_value("Global Defaults", "default_currency"),
                "country": frappe.db.get_single_value("Global Defaults", "country"),
            }
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Global Defaults Fetch Failed")
            return {}
