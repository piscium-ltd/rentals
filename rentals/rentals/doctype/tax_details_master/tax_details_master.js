// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Tax Details Master", {
	name1(frm) {
		if (frm.doc.name1) {
			frm.set_value(
				"name1",
				frm.doc.name1
					.toLowerCase()
					.replace(/\b\w/g, char => char.toUpperCase())
			);
		}
	},
});