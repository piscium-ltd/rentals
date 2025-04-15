// Copyright (c) 2025, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Meter Reading", {
	current_reading(frm) {
		calculate_units_used(frm);
	},
});

function calculate_units_used(frm) {
	const current = frm.doc.current_reading || 0;
	const initial = frm.doc.initial_reading || 0;
	const units_used = current - initial;

	frm.set_value("units_used", units_used);
}
