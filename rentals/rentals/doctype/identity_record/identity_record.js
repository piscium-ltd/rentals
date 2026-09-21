// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt


const DATE_RULES = {
	issue_date: {
		type: "past",
	},

	date_of_issue: {
		type: "past",
		relationship: ["date_of_expiry", "Date of Issue", "Date of Expiry"],
	},

	date_of_birth: {
		type: "past",
	},

	issued_on: {
		type: "past",
	},

	execution_date: {
		type: "past",
	},

	certificate_date: {
		type: "past",
	},

	effective_from: {
		type: "past",
		relationship: ["effective_to", "Effective From", "Effective To"],
	},

	expiry_date: {
		type: "future",
		relationship: ["issue_date", "Expiry Date", "Issue Date"],
	},

	date_of_expiry: {
		type: "any",
		relationship: ["date_of_issue", "Date of Expiry", "Date of Issue"],
	},

	effective_to: {
		type: "future",
		relationship: ["effective_from", "Effective To", "Effective From"],
	},
};


frappe.ui.form.on("Identity Record", {
	setup(frm) {
		configure_location_queries(frm);
		setup_date_restrictions(frm);
		update_location_field_states(frm);
	},

	refresh(frm) {
		configure_location_queries(frm);
		setup_date_restrictions(frm);
		update_location_field_states(frm);

		handle_has_expiry(frm);
		update_document_status(frm);
	},

	county(frm) {
		clear_fields(frm, [
			"constituency",
			"ward",
			"location",
			"sub_location",
		]);

		update_location_field_states(frm);
	},

	constituency(frm) {
		clear_fields(frm, [
			"ward",
			"location",
			"sub_location",
		]);

		update_location_field_states(frm);
	},

	ward(frm) {
		clear_fields(frm, [
			"location",
			"sub_location",
		]);

		update_location_field_states(frm);
	},

	location(frm) {
		clear_fields(frm, [
			"sub_location",
		]);

		update_location_field_states(frm);
	},

	surname_as_document(frm) {
		set_full_name(frm);
	},

	first_name_as_document(frm) {
		set_full_name(frm);
	},

	middle_names_as_document(frm) {
		set_full_name(frm);
	},

	has_expiry(frm) {
		handle_has_expiry(frm);
	},

	issue_date(frm) {
		validate_date(frm, "issue_date");
	},

	date_of_issue(frm) {
		validate_date(frm, "date_of_issue");
		update_document_status(frm);
	},

	date_of_birth(frm) {
		validate_date(frm, "date_of_birth");
	},

	issued_on(frm) {
		validate_date(frm, "issued_on");
	},

	execution_date(frm) {
		validate_date(frm, "execution_date");
	},

	certificate_date(frm) {
		validate_date(frm, "certificate_date");
	},

	effective_from(frm) {
		validate_date(frm, "effective_from");
	},

	expiry_date(frm) {
		validate_date(frm, "expiry_date");
	},

	date_of_expiry(frm) {
		validate_date(frm, "date_of_expiry");
		update_document_status(frm);
	},

	effective_to(frm) {
		validate_date(frm, "effective_to");
	},

	before_save(frm) {
		update_document_status(frm);
	},
});


function configure_location_queries(frm) {
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

	frm.set_query("location", () => ({
		filters: {
			ward: frm.doc.ward,
		},
	}));

	frm.set_query("sub_location", () => ({
		filters: {
			location: frm.doc.location,
		},
	}));
}


function clear_fields(frm, fields) {
	fields.forEach(fieldname => {
		if (frm.fields_dict[fieldname] && frm.doc[fieldname]) {
			frm.set_value(fieldname, null);
		}
	});
}


function update_location_field_states(frm) {
	const dependencies = {
		constituency: "county",
		ward: "constituency",
		location: "ward",
		sub_location: "location",
	};

	Object.entries(dependencies).forEach(([fieldname, parent]) => {
		if (frm.fields_dict[fieldname]) {
			frm.toggle_enable(
				fieldname,
				Boolean(frm.doc[parent])
			);
		}
	});
}


function set_full_name(frm) {
	const names = [
		frm.doc.first_name_as_document,
		frm.doc.middle_names_as_document,
		frm.doc.surname_as_document,
	].filter(Boolean);

	frm.set_value(
		"full_name_as_document",
		names.join(" ")
	);
}

function setup_date_restrictions(frm) {
	const today = frappe.datetime.get_today();

	Object.entries(DATE_RULES).forEach(([fieldname, rule]) => {
		if (!frm.fields_dict[fieldname]) {
			return;
		}

		const properties = {
			max: rule.type === "past" ? today : null,
			min: rule.type === "future" ? today : null,
		};

		Object.entries(properties).forEach(([property, value]) => {
			frm.set_df_property(
				fieldname,
				property,
				value
			);
		});
	});
}

function validate_date(frm, fieldname) {
	const value = frm.doc[fieldname];

	if (!value || !DATE_RULES[fieldname]) {
		return;
	}

	const today = frappe.datetime.get_today();
	const rule = DATE_RULES[fieldname];

	if (rule.type === "past" && value > today) {
		clear_invalid_date(
			frm,
			fieldname,
			"Date cannot be in the future."
		);

		return;
	}

	if (rule.type === "future" && value < today) {
		clear_invalid_date(
			frm,
			fieldname,
			"Date cannot be in the past."
		);

		return;
	}

	validate_date_relationship(frm, fieldname);
}


function validate_date_relationship(frm, fieldname) {
	const rule = DATE_RULES[fieldname];

	if (!rule.relationship) {
		return;
	}

	const [
		related_field,
		field_label,
		related_label,
	] = rule.relationship;

	const current_date = frm.doc[fieldname];
	const related_date = frm.doc[related_field];

	if (!current_date || !related_date) {
		return;
	}

	if (
		fieldname === "date_of_issue" &&
		current_date > related_date
	) {
		clear_invalid_date(
			frm,
			fieldname,
			`${field_label} cannot be after ${related_label}.`
		);

		return;
	}

	if (
		fieldname === "date_of_expiry" &&
		current_date < related_date
	) {
		clear_invalid_date(
			frm,
			fieldname,
			`${field_label} cannot be before ${related_label}.`
		);

		return;
	}

	if (
		rule.type === "past" &&
		current_date > related_date
	) {
		clear_invalid_date(
			frm,
			fieldname,
			`${field_label} cannot be after ${related_label}.`
		);
		return;
	}

	if (
		rule.type === "future" &&
		current_date < related_date
	) {
		clear_invalid_date(
			frm,
			fieldname,
			`${field_label} cannot be before ${related_label}.`
		);
	}
}

function clear_invalid_date(frm, fieldname, message) {
	frm.set_value(fieldname, null);

	frappe.msgprint({
		title: "Invalid Date",
		message,
		indicator: "red",
	});
}


function handle_has_expiry(frm) {
	if (!frm.fields_dict.date_of_expiry) {
		return;
	}

	const has_expiry = frm.doc.has_expiry === "Yes";

	frm.set_df_property(
		"date_of_expiry",
		"reqd",
		has_expiry ? 1 : 0
	);

	frm.set_df_property(
		"date_of_expiry",
		"hidden",
		has_expiry ? 0 : 1
	);

	if (!has_expiry && frm.doc.date_of_expiry) {
		frm.set_value("date_of_expiry", null);
	}
}


function update_document_status(frm) {
	if (
		frm.doc.evidence_type !== "Identifier Facts" ||
		frm.doc.has_expiry !== "Yes" ||
		!frm.doc.date_of_expiry
	) {
		return;
	}

	const today = frappe.datetime.get_today();

	frm.set_value(
		"document_status",
		frm.doc.date_of_expiry < today
			? "Expired"
			: "Valid"
	);
}
