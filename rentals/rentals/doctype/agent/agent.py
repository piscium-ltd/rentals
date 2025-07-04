# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils.password import update_password  

class Agent(Document):
    def after_insert(self):
        if not self.user and self.email:
            if not frappe.db.exists("User", {"email": self.email}):
                # Create User
                user = frappe.get_doc({
                    "doctype": "User",
                    "email": self.email,
                    "first_name": self.full_name,
                })
                user.insert(ignore_permissions=True)

                # ✅ Set a default password
                update_password(self.email, "agent123")

                # ✅ Assign the "Agent" role
                user.add_roles("Agent")

                # ✅ Link user to this Agent record
                self.user = user.name
                self.db_update()

                # ✅ Pop-up confirmation
                frappe.msgprint(f"✅ A new User <b>{self.user}</b> has been created and assigned the <b>Agent</b> role.")
