// Copyright (c) 2025, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Lease Agreement", {
	refresh(frm) {
		calculate_grand_total(frm);
	},
});

frappe.ui.form.on("Chargeable Services", {
	rate(frm, cdt, cdn) {
		calculate_grand_total(frm);
	},
	chargeable_services_add(frm) {
		calculate_grand_total(frm);
	},
	chargeable_services_remove(frm) {
		calculate_grand_total(frm);
	},
});

function calculate_grand_total(frm) {
	let total = 0;
	(frm.doc.chargeable_services || []).forEach((row) => {
		total += flt(row.rate);
	});
	frm.set_value("grand_total", total);
}
