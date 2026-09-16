# Copyright (c) 2026, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class IdentityRecord(Document):
	pass


def expire_identity_records():

	today = frappe.utils.today()

	records = frappe.get_all(
		"Identity Record",
		filters={
			"evidence_type": "Identifier Facts",
			"has_expiry": "Yes",
			"date_of_expiry": ["<", today],
			"document_status": ["!=", "Expired"],
		},
		pluck="name",
	)

	for name in records:
		frappe.db.set_value(
			"Identity Record",
			name,
			"document_status",
			"Expired",
			update_modified=False,
		)