# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class MeterReading(Document):
    def before_save(self):
        """Validate readings and automatically calculate units used before saving the document."""
        if self.initial_reading is not None and self.current_reading is not None:
            if self.current_reading <= self.initial_reading:
                frappe.throw("🚫 Current reading must be greater than initial reading.")

            self.units_used = self.current_reading - self.initial_reading
        else:
            self.units_used = 0

    def on_submit(self):
        """Handle tasks after submission: update meter reading and create utility bill log."""
        if self.meter and self.current_reading is not None:
            frappe.db.set_value("Meter", self.meter, "meter_reading", self.current_reading)
            frappe.msgprint(f"✅ Updated meter '{self.meter}' reading to {self.current_reading}")

        self.create_utility_bill_log()

    def create_utility_bill_log(self):
        """Create Utility Bill Logs for the submitted meter reading."""
        if not self.meter:
            frappe.msgprint("⚠️ No meter linked to this reading.")
            return

        meter_doc = frappe.get_doc("Meter", self.meter)

        if meter_doc.meter_method == "Per Unit":
            # Find tenant from the unit
            if not meter_doc.unit:
                frappe.throw("⚠️ Meter is 'Per Unit' but no Unit is linked.")
            lease_agreements = frappe.get_all(
                "Lease Agreement",
                filters={"unit": meter_doc.unit, "status": "Active"},
                fields=["tenant"]
            )
            if not lease_agreements:
                frappe.msgprint("⚠️ No active lease agreement found for the unit.")
                return

            tenant = lease_agreements[0].get("tenant")
            tenant_doc = frappe.get_doc("Tenant", tenant)

            # Create one Utility Bill Log
            utility_bill_log = frappe.get_doc({
                "doctype": "Utility Bill Log",
                "meter_reading": self.name,
                "units_used": self.units_used,
                "utility_provider": meter_doc.utility_provider,
                "utility": meter_doc.utility,
                "meter_method": meter_doc.meter_method,
                "status": "Open",
                "customer": tenant_doc.customer
            })
            utility_bill_log.insert()
            frappe.msgprint(f"✅ Created Utility Bill Log: {utility_bill_log.name}")

        elif meter_doc.meter_method == "Full Property":
            # Find all tenants under the property
            if not meter_doc.property:
                frappe.throw("⚠️ Meter is 'Full Property' but no Property is linked.")

            lease_agreements = frappe.get_all(
                "Lease Agreement",
                filters={"property": meter_doc.property, "status": "Active"},
                fields=["tenant"]
            )
            if not lease_agreements:
                frappe.msgprint("⚠️ No active lease agreements found for the property.")
                return

            total_tenants = len(lease_agreements)
            share_per_tenant = self.units_used / total_tenants if total_tenants else 0

            for lease in lease_agreements:
                tenant_doc = frappe.get_doc("Tenant", lease.get("tenant"))

                utility_bill_log = frappe.get_doc({
                    "doctype": "Utility Bill Log",
                    "meter_reading": self.name,
                    "units_used": share_per_tenant,
                    "utility_provider": meter_doc.utility_provider,
                    "utility": meter_doc.utility,
                    "meter_method": meter_doc.meter_method,
                    "status": "Open",
                    "customer": tenant_doc.customer
                })
                utility_bill_log.insert()

            frappe.msgprint(f"✅ Created {total_tenants} Utility Bill Logs for Full Property meter.")

    def on_cancel(self):
        """Reverse changes made during submission: restore previous meter reading and cancel related utility bill logs."""
        try:
            if self.meter and self.initial_reading is not None:
                frappe.db.set_value("Meter", self.meter, "meter_reading", self.initial_reading)
                frappe.msgprint(f"✅ Reverted meter '{self.meter}' reading to {self.initial_reading}")

            # Find all Utility Bill Logs linked to this meter reading
            utility_bill_logs = frappe.get_all(
                "Utility Bill Log",
                filters={"meter_reading": self.name},
                fields=["name"]
            )

            if utility_bill_logs:
                for log in utility_bill_logs:
                    utility_bill_log = frappe.get_doc("Utility Bill Log", log.name)
                    utility_bill_log.status = "Cancelled"
                    utility_bill_log.save(ignore_permissions=True)
                frappe.msgprint(f"✅ Cancelled {len(utility_bill_logs)} Utility Bill Logs linked to this reading.")
            else:
                frappe.msgprint("ℹ️ No Utility Bill Logs found to reverse.")
        except Exception:
            frappe.log_error(frappe.get_traceback(), "MeterReading on_cancel Error")
            frappe.msgprint("⚠️ An error occurred while reversing changes. Please check the error log.")
