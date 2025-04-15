# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

class MeterReading(Document):
    def before_save(self):
        """Automatically calculate units used before saving the document."""
        if self.initial_reading is not None and self.current_reading is not None:
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
        """Create a Utility Bill Log for the submitted meter reading."""
        if not self.meter:
            frappe.msgprint("⚠️ No meter linked to this reading.")
            return

        meter_doc = frappe.get_doc("Meter", self.meter)

        # Get the active lease agreement for the meter's unit
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

        # Create and insert Utility Bill Log
        utility_bill_log = frappe.get_doc({
            "doctype": "Utility Bill Log",
            "meter_reading": self.name,
            "units_used": self.units_used,
            "meter_type": meter_doc.meter_type,
            "status": "Open",
            "customer": tenant_doc.customer
        })
        utility_bill_log.insert()
        frappe.msgprint(f"✅ Created Utility Bill Log: {utility_bill_log.name}")
