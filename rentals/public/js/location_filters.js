(() => {
	const doctypes = ["Landlord", "Tenant", "Property", "Agent"];

	doctypes.forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			setup(frm) {
				// Constituency depends on County
				frm.set_query("constituency", () => ({
					filters: {
						county: frm.doc.county,
					},
				}));

				// Ward depends on Constituency
				frm.set_query("ward", () => ({
					filters: {
						constituency: frm.doc.constituency,
					},
				}));

				// Location depends on Ward
				frm.set_query("location", () => ({
					filters: {
						ward: frm.doc.ward,
					},
				}));
			},

			county(frm) {
				frm.set_value("constituency", null);
				frm.set_value("ward", null);
				frm.set_value("location", null);
			},

			constituency(frm) {
				frm.set_value("ward", null);
				frm.set_value("location", null);
			},

			ward(frm) {
				frm.set_value("location", null);
			},
		});
	});
})();
