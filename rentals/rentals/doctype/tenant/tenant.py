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
                _("✅ Tenant created successfully and linked to Customer <b>{0}</b>.").format(
                    customer.customer_name
                ),
                indicator="green",
                alert=True,
            )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Tenant after_insert Error")
            frappe.throw(_("❌ Failed to create and link Customer for Tenant. Check error logs."))

    def _create_customer(self):
        """Create a new Customer for this Tenant."""
        try:
            customer_name = self._get_customer_name()
            customer_group = self._get_valid_customer_group()

            existing_customer = frappe.db.exists("Customer", {"customer_name": customer_name})
            if existing_customer:
                return frappe.get_doc("Customer", existing_customer)

            customer = frappe.get_doc(
                {
                    "doctype": "Customer",
                    "customer_name": customer_name,
                    "customer_type": self._get_customer_type(),
                    "email_id": self.email,
                    "mobile_no": self._get_mobile_no(),
                    "customer_group": customer_group,
                }
            )

            customer.insert(ignore_permissions=True)
            return customer

        except Exception:
            frappe.log_error(frappe.get_traceback(), "Customer Creation Failed")
            frappe.throw(_("❌ Failed to create Customer for Tenant. Check error logs."))

    def _get_customer_name(self):
        """Resolve Customer name from tenant data."""
        if self.tenant_type == "Individual":
            return self.full_name

        return self.company_name or self.full_name

    def _get_customer_type(self):
        """Map Tenant type to ERPNext Customer type."""
        if self.tenant_type == "Company":
            return "Company"

        return "Individual"

    def _get_mobile_no(self):
        """Resolve tenant mobile number safely."""
        return self.mobile_no or self.phone_number

    def _get_valid_customer_group(self):
        """
        Return a non-group Customer Group.

        ERPNext does not allow Customer.customer_group to be a group node like:
        - All Customer Groups

        Priority:
        1. Selling Settings default customer group, if it exists and is non-group.
        2. Existing non-group 'Tenant Customers'.
        3. Create non-group 'Tenant Customers' under the Customer Group root.
        """
        default_group = frappe.db.get_single_value("Selling Settings", "customer_group")

        if default_group and self._is_non_group_customer_group(default_group):
            return default_group

        tenant_group = "Tenant Customers"

        if frappe.db.exists("Customer Group", tenant_group):
            if self._is_non_group_customer_group(tenant_group):
                return tenant_group

            tenant_group = "Tenant Customers - Leaf"
            if frappe.db.exists("Customer Group", tenant_group):
                if self._is_non_group_customer_group(tenant_group):
                    return tenant_group

        root_group = self._get_customer_group_root()

        customer_group = frappe.get_doc(
            {
                "doctype": "Customer Group",
                "customer_group_name": tenant_group,
                "parent_customer_group": root_group,
                "is_group": 0,
            }
        )
        customer_group.insert(ignore_permissions=True)

        return customer_group.name

    def _is_non_group_customer_group(self, customer_group):
        """Check whether a Customer Group exists and is a leaf/non-group node."""
        is_group = frappe.db.get_value("Customer Group", customer_group, "is_group")

        if is_group is None:
            return False

        return not cint(is_group)

    def _get_customer_group_root(self):
        """Find the root Customer Group."""
        root_group = frappe.db.get_value("Customer Group", {"is_group": 1, "parent_customer_group": ["is", "not set"]})

        if root_group:
            return root_group

        if frappe.db.exists("Customer Group", "All Customer Groups"):
            return "All Customer Groups"

        root_group = frappe.db.get_value("Customer Group", {"is_group": 1}, "name")
        if root_group:
            return root_group

        frappe.throw(
            _(
                "No root Customer Group found. Please create a group Customer Group first, "
                "for example <b>All Customer Groups</b>."
            )
        )
