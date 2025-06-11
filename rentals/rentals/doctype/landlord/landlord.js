// Copyright (c) 2025, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Landlord", {
	company_name: function (frm) {
		if (frm.doc.__islocal && frm.doc.company_name) {
			frm.set_value("abbr", get_abbreviation(frm.doc.company_name));
		}
	},
	full_name: function (frm) {
		if (frm.doc.__islocal && frm.doc.full_name) {
			frm.set_value("abbr", get_abbreviation(frm.doc.full_name));
		}
	},
});

// Utility function to get abbreviation from a name
function get_abbreviation(name) {
	return name
		.split(" ")
		.filter((part) => part.trim().length > 0)
		.map((part) => part[0].toUpperCase())
		.join("");
}
