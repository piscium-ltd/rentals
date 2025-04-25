// Copyright (c) 2025, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Meter", {
	refresh(frm) {
		frm.set_query("utility", () => ({
			filters: {
				item_group: "Utility",
				has_variants: 1,
			},
		}));
	},
});
