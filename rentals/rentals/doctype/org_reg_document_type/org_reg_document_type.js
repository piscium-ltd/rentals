// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Org Reg Document Type", {
	document_type(frm) {
		if (frm.doc.document_type) {
			frm.set_value(
				"document_type",
				frm.doc.document_type
					.toLowerCase()
					.replace(/\b\w/g, char => char.toUpperCase())
			);
		}
	},
});