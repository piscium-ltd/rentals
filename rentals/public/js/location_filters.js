(() => {
	const locationFieldByDoctype = {
		Landlord: "location",
		Tenant: "location",
		Property: "rental_location",
		Agent: "location",
	};

	Object.entries(locationFieldByDoctype).forEach(([doctype, locationField]) => {
		const enforceHierarchy = doctype === "Property";

		frappe.ui.form.on(doctype, {
			setup(frm) {
				configure_location_queries(frm, locationField);
				update_location_field_states(frm, locationField, enforceHierarchy);
			},

			refresh(frm) {
				update_location_field_states(frm, locationField, enforceHierarchy);
			},

			county(frm) {
				clear_fields(frm, ["constituency", "ward", locationField, "sub_location"]);
				update_location_field_states(frm, locationField, enforceHierarchy);
			},

			constituency(frm) {
				clear_fields(frm, ["ward", locationField, "sub_location"]);
				update_location_field_states(frm, locationField, enforceHierarchy);
			},

			ward(frm) {
				clear_fields(frm, [locationField, "sub_location"]);
				update_location_field_states(frm, locationField, enforceHierarchy);
			},

			[locationField](frm) {
				clear_fields(frm, ["sub_location"]);
				update_location_field_states(frm, locationField, enforceHierarchy);
			},
		});
	});

	function configure_location_queries(frm, locationField) {
		frm.set_query("constituency", () => ({
			filters: {
				county: frm.doc.county,
			},
		}));

		frm.set_query("ward", () => ({
			filters: {
				constituency: frm.doc.constituency,
			},
		}));

		frm.set_query(locationField, () => ({
			filters: {
				ward: frm.doc.ward,
			},
		}));

		frm.set_query("sub_location", () => ({
			filters: {
				location: frm.doc[locationField],
			},
		}));
	}

	function clear_fields(frm, fields) {
		fields.forEach((fieldname) => {
			if (frm.fields_dict[fieldname] && frm.doc[fieldname]) {
				frm.set_value(fieldname, null);
			}
		});
	}

	function update_location_field_states(frm, locationField, enforceHierarchy) {
		if (!enforceHierarchy) return;

		if (frm.fields_dict.constituency) {
			frm.toggle_enable("constituency", Boolean(frm.doc.county));
		}
		if (frm.fields_dict.ward) {
			frm.toggle_enable("ward", Boolean(frm.doc.constituency));
		}
		if (frm.fields_dict[locationField]) {
			frm.toggle_enable(locationField, Boolean(frm.doc.ward));
		}
		if (frm.fields_dict.sub_location) {
			frm.toggle_enable("sub_location", Boolean(frm.doc[locationField]));
		}
	}
})();
