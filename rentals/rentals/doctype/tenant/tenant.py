# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, now_datetime


class Tenant(Document):
    def validate(self):
        self._sync_sms_opt_out_timestamp()

    def _sync_sms_opt_out_timestamp(self):
        """Track when a tenant opts out of SMS."""
        if not hasattr(self, "allow_sms"):
            return

        if not cint(self.allow_sms):
            if not self.sms_opt_out_on:
                self.sms_opt_out_on = now_datetime()
        else:
            self.sms_opt_out_on = None
            self.sms_opt_out_reason = None

    def after_insert(self):
        """Create a Customer record for this Tenant and link it."""
        try:
            customer = self._create_customer()
            self.db_set("customer", customer.name)

            frappe.msgprint(
                _("✅ Tenant created successfully and linked to Customer <b>{0}</b>.").format(customer.customer_name),
                indicator="green", alert=True
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Tenant after_insert Error")
            frappe.throw(_("❌ Failed to create and link Customer for Tenant. Check error logs."))

    def _create_customer(self):
        """Create a new Customer for this Tenant."""
        try:
            customer_name = self.full_name if self.tenant_type == "Individual" else self.company_name
            customer_group = frappe.db.get_single_value('Selling Settings', 'customer_group') or "All Customer Groups"

            customer = frappe.get_doc({
                "doctype": "Customer",
                "customer_name": customer_name,
                "customer_type": self.tenant_type,
                "email_id": self.email,
                "customer_group": customer_group
            })
            customer.insert(ignore_permissions=True)
            return customer
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Customer Creation Failed")
            frappe.throw(_("❌ Failed to create Customer for Tenant. Check error logs."))
