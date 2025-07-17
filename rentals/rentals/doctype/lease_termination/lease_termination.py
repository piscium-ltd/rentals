# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class LeaseTermination(Document):
    def on_submit(self):
        # Update lease status to Terminated
        lease = frappe.get_doc("Lease Agreement", self.lease_agreement)       
        lease.status = "Terminated"
        lease.save()

        frappe.msgprint(f"✅ Lease Agreement <b>{lease.name}</b> has been <b>Terminated</b>.",indicator="green", alert=True)

        # Update unit status to Vacant
        unit = frappe.get_doc("Unit", self.unit)
        unit.status = "Vacant"
        unit.save()

        frappe.msgprint(f"✅ Unit <b>{unit.name}</b> is now <b>Vacant</b>.",indicator="green", alert=True)
