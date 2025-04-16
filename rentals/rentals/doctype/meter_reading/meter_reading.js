// Copyright (c) 2025, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Meter Reading", {
	current_reading(frm) {
		calculate_units_used(frm);
	},
});

function calculate_units_used(frm) {
	const current = frm.doc.current_reading;
	const initial = frm.doc.initial_reading;

	if (initial && current) {
		if (current <= initial) {
			frappe.msgprint("🚫 Current reading must be greater than initial reading.");
			return;
		}
		const units_used = current - initial;
		frm.set_value("units_used", units_used);
	} else {
		frm.set_value("units_used", 0);
	}
}
