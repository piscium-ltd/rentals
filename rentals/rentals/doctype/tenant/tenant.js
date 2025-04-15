// Copyright (c) 2025, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Tenant", {
	refresh(frm) {
        frm.set_query("unit", () => ({
            filters:{
                property: frm.doc.property
            },
        }));
	},
});
