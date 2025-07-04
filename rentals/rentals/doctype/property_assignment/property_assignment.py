# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PropertyAssignment(Document):
    def on_submit(self):
        user = frappe.db.get_value("Agent", self.agent, "user")

        if not user:
            frappe.throw(_("❌ The selected agent does not have a linked user account."))

        if not frappe.db.exists("User Permission", {
            "user": user,
            "allow": "Property",
            "for_value": self.property
        }):
            frappe.get_doc({
                "doctype": "User Permission",
                "user": user,
                "allow": "Property",
                "for_value": self.property
            }).insert(ignore_permissions=True)

            frappe.msgprint(_("✅ Permission added: <b>{0}</b> can now access Property <b>{1}</b>.").format(user, self.property))

    def on_cancel(self):
        user = frappe.db.get_value("Agent", self.agent, "user")

        if not user:
            return

        permissions = frappe.get_all("User Permission", {
            "user": user,
            "allow": "Property",
            "for_value": self.property
        })

        for perm in permissions:
            frappe.delete_doc("User Permission", perm.name, ignore_permissions=True)

        frappe.msgprint(_("🗑️ Permission removed: <b>{0}</b> can no longer access Property <b>{1}</b>.").format(user, self.property))
