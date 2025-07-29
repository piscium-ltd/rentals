# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
import random
import re
from frappe import _
from frappe.model.document import Document

class Agent(Document):
    def validate(self):
        """Validate KRA PIN format."""
        if self.kra_pin:
            self.kra_pin = self.kra_pin.strip().upper()
            if not re.fullmatch(r"[AP]\d{9}[A-Z]", self.kra_pin):
                frappe.throw(
                    _("❌ Invalid KRA PIN format. Use format like <b>A123456789B</b> or <b>P051234567K</b>.")
                )

    def after_insert(self):
        """Handle post-insert tasks: abbreviation, company, user, customer, and supplier creation."""
        try:
            abbr = self._get_abbreviation()
            self.db_set("abbr", abbr)

            company_name = self.company_name if self.agent_type == "Company" else abbr

            # Create company if it doesn't exist
            if not frappe.db.exists("Company", {"company_name": company_name}):
                self._create_company(company_name, abbr)

            self.db_set("company", company_name)
            # Create user if email is provided and user doesn't exist
            if self.email and not frappe.db.exists("User", self.email):
                display_name = company_name if self.agent_type == "Company" else self.full_name
                self._create_user(display_name)

            # Create Customer and Supplier
            self._create_customer(company_name)
            self._create_supplier(company_name)

        except Exception as e:
            frappe.log_error(message=frappe.get_traceback(), title="Agent after_insert Error")
            frappe.throw(_("❌ An error occurred while setting up Agent details. Please check logs."))

    # -------------------------------
    # Private Helper Methods
    # -------------------------------

    def _create_company(self, company_name, abbr):
        """Create a new Company and link it to the Agent."""
        try:
            defaults = self._get_global_defaults()

            company = frappe.get_doc({
                "doctype": "Company",
                "company_name": company_name,
                "abbr": abbr,
                "default_currency": defaults.get("default_currency", "KES"),
                "country": defaults.get("country", "Kenya"),
                "tax_id": self.kra_pin,
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
            frappe.throw(_("❌ Failed to create associated Company for this Agent. Check error logs."))

    def _create_user(self, name):
        """Create a user for the Agent and assign permissions."""
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

            # Assign permissions
            self._assign_user_permission(user.name, "agent", self.name)
            self._assign_user_permission(user.name, "Company", self.company)

            frappe.msgprint(_("✅ User <b>{0}</b> created successfully.").format(user.name),indicator="green", alert=True)

        except Exception:
            frappe.log_error(frappe.get_traceback(), "User Creation Failed")
            frappe.throw(_("❌ Failed to create user for this Agent. Check error logs."))

    def _assign_user_permission(self, user, doctype, value):
        """Assign user permission for a specific doctype and value."""
        try:
            frappe.get_doc({
                "doctype": "User Permission",
                "user": user,
                "allow": doctype,
                "for_value": value,
            }).insert(ignore_permissions=True)
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Failed to assign permission for {doctype}")

    def _create_customer(self, customer_name):
        """Create a Customer for the Agent."""
        try:
            if not frappe.db.exists("Customer", {"customer_name": customer_name}):
                customer = frappe.get_doc({
                    "doctype": "Customer",
                    "customer_name": customer_name,
                    "email_id": self.email,
                    "customer_type": "Company" if self.agent_type == "Company" else "Individual"
                })
                customer.insert(ignore_permissions=True)
                frappe.msgprint(
                _("✅ Customer created successfully <b>{0}</b>.").format(customer_name),indicator="green", alert=True
            )
                self.db_set("customer", customer.name)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Customer Creation Failed")
            frappe.throw(_("❌ Failed to create Customer for this Agent. Check logs."))

    def _create_supplier(self, supplier_name):
        """Create a Supplier for the Agent."""
        try:
            if not frappe.db.exists("Supplier", {"supplier_name": supplier_name}):
                supplier = frappe.get_doc({
                    "doctype": "Supplier",
                    "supplier_name": supplier_name,
                    "supplier_type": "Company" if self.agent_type == "Company" else "Individual"
                })
                supplier.insert(ignore_permissions=True)
                frappe.msgprint(
                _("✅ Supplier created successfully <b>{0}</b>.").format(supplier_name),indicator="green", alert=True
            )
                self.db_set("supplier", supplier.name)
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Supplier Creation Failed")
            frappe.throw(_("❌ Failed to create Supplier for this Agent. Check logs."))

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
        """Fetch global defaults once to reduce DB calls."""
        try:
            return {
                "default_company": frappe.db.get_single_value("Global Defaults", "default_company"),
                "default_currency": frappe.db.get_single_value("Global Defaults", "default_currency"),
                "country": frappe.db.get_single_value("Global Defaults", "country"),
            }
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Global Defaults Fetch Failed")
            return {}
