# Copyright (c) 2026, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class IdentityRecord(Document):
	pass


def expire_identity_records():

	today = frappe.utils.today()

	# Mark expired records
	expired_records = frappe.get_all(
		"Identity Record",
		filters={
			"evidence_type": "Identifier Facts",
			"has_expiry": "Yes",
			"date_of_expiry": ["<", today],
			"document_status": ["!=", "Expired"],
		},
		pluck="name",
	)

	for name in expired_records:
		frappe.db.set_value(
			"Identity Record",
			name,
			"document_status",
			"Expired",
			update_modified=False,
		)

	# Mark valid records
	valid_records = frappe.get_all(
		"Identity Record",
		filters={
			"evidence_type": "Identifier Facts",
			"has_expiry": "Yes",
			"date_of_expiry": [">=", today],
			"document_status": ["!=", "Valid"],
		},
		pluck="name",
	)

	for name in valid_records:
		frappe.db.set_value(
			"Identity Record",
			name,
			"document_status",
			"Valid",
			update_modified=False,
		)