// Copyright (c) 2025, Piscium Solutions LTD and contributors
// For license information, please see license.txt

function apply_rate_type_state(frm) {
	const is_flat = frm.doc.rate_type === "Flat";
	const is_slab = frm.doc.rate_type === "Slab";

	// Keep Desk requiredness synchronized immediately with the selected mode.
	// The DocType also has matching mandatory_depends_on rules and the Python
	// controller enforces the same invariant for non-Desk saves.
	frm.toggle_reqd("flat_rate", is_flat);
	frm.toggle_reqd("slab_rate", is_slab);
}

frappe.ui.form.on("Utility Rate", {
	refresh(frm) {
		apply_rate_type_state(frm);
	},

	async rate_type(frm) {
		if (frm.doc.rate_type === "Flat") {
			if ((frm.doc.slab_rate || []).length) {
				frm.clear_table("slab_rate");
				frm.refresh_field("slab_rate");
			}
		} else if (frm.doc.rate_type === "Slab") {
			if (frm.doc.flat_rate !== null && frm.doc.flat_rate !== undefined) {
				await frm.set_value("flat_rate", null);
			}
		}

		apply_rate_type_state(frm);
	},
});
