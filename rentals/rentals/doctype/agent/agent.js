// Copyright (c) 2025, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Agent", {
	refresh(frm) {},
	kra_pin(frm) {
		// validate KRA pin
		const pin = frm.doc.kra_pin?.trim().toUpperCase();
		const regex = /^[AP]{1}\d{9}[A-Z]{1}$/;

		if (!pin || regex.test(pin)) {
			// Clear error styling and message if valid
			frm.set_df_property("kra_pin", "description", "");
		} else {
			// Set error message below the field
			frm.set_df_property("kra_pin", "description", "Invalid KRA PIN format");
			// Highlight the field border in red
			setTimeout(() => {
				frm.fields_dict.kra_pin.$wrapper
					.find(".help-box")
					.removeClass("text-extra-muted")
					.css("color", "red");
			}, 100);
		}
	},
});
