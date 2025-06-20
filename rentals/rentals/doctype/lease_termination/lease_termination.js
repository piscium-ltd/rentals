// Copyright (c) 2025, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Lease Termination", {
	refresh(frm) {
		frm.set_query("property", () => ({
			filters: {
				landlord: frm.doc.landlord,
			},
		}));
		frm.set_query("unit", () => ({
			filters: {
				property: frm.doc.property,
				status: "Occupied",
			},
		}));
		frm.set_query("lease_agreement", () => ({
			filters: {
				unit: frm.doc.unit,
				status: "Active",
			},
		}));
	},
});
