# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _

class Agent(Document):
    def after_insert(self):
        self.create_user()

    def create_user(self):
        if self.email and not frappe.db.exists("User", self.email):
            user = frappe.get_doc({
                "doctype": "User",
                "email": self.email,
                "first_name": self.full_name,
                "send_welcome_email": 0,
                "role_profiles": [
                    {
                        "role_profile": "Rentals"
                    }
                ]
            })
            user.insert(ignore_permissions=True)

            self.db_set("user", user.name)

            frappe.get_doc({
                "doctype": "User Permission",
                "user": user.name,
                "allow": "Agent",
                "for_value": self.name
            }).insert(ignore_permissions=True)

            frappe.msgprint(_("✅ User <b>{0}</b> created successfully.").format(user.name))
