# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import random
import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime, now


PROVISIONING_QUEUE = "long"
PROVISIONING_METHOD = "rentals.rentals.doctype.landlord.landlord.provision_landlord"


class Landlord(Document):
    def validate(self):
        """Validate KRA PIN format and SMS preferences."""
        self._sync_sms_opt_out_timestamp()
        if self.kra_pin:
            self.kra_pin = self.kra_pin.strip().upper()
            if not re.fullmatch(r"[AP]\d{9}[A-Z]", self.kra_pin):
                frappe.throw(
                    _("❌ Invalid KRA PIN format. Use format like <b>A123456789B</b> or <b>P051234567K</b>.")
                )

    def _sync_sms_opt_out_timestamp(self):
        """Track when a landlord opts out of SMS."""
        if not hasattr(self, "allow_sms"):
            return

        if not cint(self.allow_sms):
            if not self.sms_opt_out_on:
                self.sms_opt_out_on = now_datetime()
        else:
            self.sms_opt_out_on = None
            self.sms_opt_out_reason = None

    def after_insert(self):
        """Save quickly, then provision expensive linked records in a worker."""
        abbr = self._get_abbreviation()
        self.db_set("abbr", abbr, update_modified=False)
        self.db_set("setup_status", "Pending", update_modified=False)
        self.db_set("setup_error", None, update_modified=False)
        self.db_set("setup_completed_on", None, update_modified=False)
        self._enqueue_provisioning()

    def _enqueue_provisioning(self):
        """Queue provisioning only after the landlord transaction commits."""
        frappe.enqueue(
            PROVISIONING_METHOD,
            queue=PROVISIONING_QUEUE,
            enqueue_after_commit=True,
            job_id=f"landlord-provision-{self.name}",
            deduplicate=True,
            landlord_name=self.name,
        )

    def _provision_related_records(self):
        """Idempotently create and link Company, User, Customer and Supplier."""
        self.db_set("setup_status", "In Progress", update_modified=False)
        self.db_set("setup_error", None, update_modified=False)

        company_name = self.company_name if self.landlord_type == "Company" else self.abbr
        company = self._ensure_company(company_name, self.abbr)
        self.db_set("company", company, update_modified=False)
        self.company = company

        if self.email:
            display_name = company_name if self.landlord_type == "Company" else self.full_name
            user = self._ensure_user(display_name)
            self.db_set("user", user, update_modified=False)
            self.user = user
            self._ensure_user_permission(user, "Landlord", self.name)
            self._ensure_user_permission(user, "Company", company)

        customer = self._ensure_customer(company_name)
        self.db_set("customer", customer, update_modified=False)
        self.customer = customer

        supplier = self._ensure_supplier(company_name)
        self.db_set("supplier", supplier, update_modified=False)
        self.supplier = supplier

        self.db_set("setup_completed_on", now(), update_modified=False)
        self.db_set("setup_status", "Completed", update_modified=False)
        self.db_set("setup_error", None, update_modified=False)

    # -------------------------------
    # Private Helper Methods
    # -------------------------------

    def _ensure_company(self, company_name, abbr):
        """Return an existing Company or create it."""
        existing = frappe.db.exists("Company", {"company_name": company_name})
        if existing:
            return existing

        defaults = self._get_global_defaults()
        company = frappe.get_doc({
            "doctype": "Company",
            "company_name": company_name,
            "abbr": abbr,
            "default_currency": defaults.get("default_currency") or "KES",
            "country": defaults.get("country") or "Kenya",
            "tax_id": self.kra_pin,
            "create_chart_of_accounts_based_on": "Existing Company",
            "existing_company": defaults.get("default_company"),
        })
        company.insert(ignore_permissions=True)
        return company.name

    def _ensure_user(self, name):
        """Return an existing user or create one with the Rentals role profile."""
        if frappe.db.exists("User", self.email):
            return self.email

        user = frappe.get_doc({
            "doctype": "User",
            "email": self.email,
            "first_name": name,
            "send_welcome_email": 0,
            "role_profiles": [{"role_profile": "Rentals"}],
        })
        user.insert(ignore_permissions=True)
        return user.name

    def _ensure_user_permission(self, user, doctype, value):
        """Create a User Permission once; retries must not create duplicates."""
        if not user or not value:
            return

        filters = {"user": user, "allow": doctype, "for_value": value}
        if frappe.db.exists("User Permission", filters):
            return

        frappe.get_doc({
            "doctype": "User Permission",
            **filters,
        }).insert(ignore_permissions=True)

    def _ensure_customer(self, customer_name):
        """Return an existing Customer or create it."""
        existing = frappe.db.exists("Customer", {"customer_name": customer_name})
        if existing:
            return existing

        customer = frappe.get_doc({
            "doctype": "Customer",
            "customer_name": customer_name,
            "customer_type": "Company" if self.landlord_type == "Company" else "Individual",
        })
        customer.insert(ignore_permissions=True)
        return customer.name

    def _ensure_supplier(self, supplier_name):
        """Return an existing Supplier or create it."""
        existing = frappe.db.exists("Supplier", {"supplier_name": supplier_name})
        if existing:
            return existing

        supplier = frappe.get_doc({
            "doctype": "Supplier",
            "supplier_name": supplier_name,
            "supplier_type": "Company" if self.landlord_type == "Company" else "Individual",
        })
        supplier.insert(ignore_permissions=True)
        return supplier.name

    def _get_abbreviation(self):
        """Generate a unique 3-letter abbreviation."""
        safe_charset = "ACDEFHJKMNPRTVWXY"
        blacklist = {"FAP", "FAT", "WET", "WTF"}
        max_attempts = 5000

        try:
            for _ in range(max_attempts):
                abbr = "".join(random.choices(safe_charset, k=3))
                if (
                    abbr not in blacklist
                    and not frappe.db.exists("Company", {"abbr": abbr})
                    and not frappe.db.exists("Landlord", {"abbr": abbr})
                ):
                    return abbr
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Abbreviation Generation Failed")

        frappe.throw(_("❌ Unable to generate a unique abbreviation after {0} attempts.").format(max_attempts))

    def _get_global_defaults(self):
        """Fetch global defaults once to reduce DB calls."""
        return {
            "default_company": frappe.db.get_single_value("Global Defaults", "default_company"),
            "default_currency": frappe.db.get_single_value("Global Defaults", "default_currency"),
            "country": frappe.db.get_single_value("Global Defaults", "country"),
        }


@frappe.whitelist()
def retry_landlord_setup(landlord_name):
    """Retry failed/pending provisioning without blocking the Desk request."""
    landlord = frappe.get_doc("Landlord", landlord_name)
    landlord.check_permission("write")

    if landlord.setup_status == "Completed":
        return {"status": "Completed"}

    landlord.db_set("setup_status", "Pending", update_modified=False)
    landlord.db_set("setup_error", None, update_modified=False)
    landlord.db_set("setup_completed_on", None, update_modified=False)
    landlord._enqueue_provisioning()
    return {"status": "Pending"}


def provision_landlord(landlord_name):
    """Background entry point for expensive landlord provisioning."""
    try:
        landlord = frappe.get_doc("Landlord", landlord_name)
        if landlord.setup_status == "Completed":
            return
        landlord._provision_related_records()
    except Exception as exc:
        # Preserve any successfully-created linked records; the workflow is
        # idempotent, so an administrator can safely retry from the form.
        error_text = str(exc) or exc.__class__.__name__
        frappe.db.set_value(
            "Landlord",
            landlord_name,
            {
                "setup_status": "Failed",
                "setup_error": error_text[:500],
                "setup_completed_on": None,
            },
            update_modified=False,
        )
        frappe.log_error(frappe.get_traceback(), "Landlord Provisioning Failed")
