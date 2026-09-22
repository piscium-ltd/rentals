// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt

const NAME_FIELDS = [
	"first_name_as_document",
	"middle_names_as_document",
	"surname_as_document",
];

const IDENTITY_RECORD_CONTEXT_KEY =
	"jurisdiction_profile_release_identity_record_context";

const IDENTITY_RECORD_CREATED_KEY =
	"jurisdiction_profile_release_identity_record_created";

const DATE_RULES = {
	issue_date: {
		type: "past",
	},

	date_of_issue: {
		type: "past",
		relationship: [
			"date_of_expiry",
			"Date of Issue",
			"Date of Expiry",
		],
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
		relationship: [
			"effective_to",
			"Effective From",
			"Effective To",
		],
	},

	expiry_date: {
		type: "future",
		relationship: [
			"issue_date",
			"Expiry Date",
			"Issue Date",
		],
	},

	date_of_expiry: {
		type: "any",
		relationship: [
			"date_of_issue",
			"Date of Expiry",
			"Date of Issue",
		],
	},

	effective_to: {
		type: "future",
		relationship: [
			"effective_from",
			"Effective To",
			"Effective From",
		],
	},
};

frappe.ui.form.on("Identity Record", {
	setup(frm) {
		configure_location_queries(frm);
		setup_date_restrictions(frm);
		update_location_field_states(frm);
	},

	onload(frm) {
		console.log(
			"[IR] onload:",
			frm.doc.name,
			"new:",
			frm.is_new()
		);

		/*
		 * Capture route_options immediately.
		 *
		 * Frappe can consume route_options while creating
		 * the new document. We keep a copy on the form so
		 * the context is still available during rendering.
		 */
		if (
			frm.is_new() &&
			frappe.route_options
		) {
			frm.__jpr_route_options = {
				...frappe.route_options,
			};

			console.log(
				"[IR] Captured route options:",
				frm.__jpr_route_options
			);
		}
	},

	onload_post_render(frm) {
		console.log(
			"[IR] onload_post_render:",
			frm.doc.name,
			"new:",
			frm.is_new()
		);

		if (
			frm.is_new() &&
			!frm.__jpr_identity_context_restored
		) {
			const restored =
				restore_identity_record_context(
					frm
				);

			/*
			 * Only mark the context as restored when
			 * an actual Release context or route options
			 * were found and applied.
			 */
			if (restored) {
				frm.__jpr_identity_context_restored =
					true;

				console.log(
					"[IR] Context restoration completed."
				);
			} else {
				console.log(
					"[IR] Context not available yet."
				);

				/*
				 * One retry gives Frappe time to finish
				 * consuming route options / initializing
				 * the new document.
				 */
				setTimeout(() => {
			
					if (
						frm.is_new() &&
						!frm.__jpr_identity_context_restored
					) {
						const restored =
							restore_identity_record_context(frm);

						if (!restored) {
							setTimeout(() => {
								if (
									frm.is_new() &&
									!frm.__jpr_identity_context_restored
								) {
									const retry_result =
										restore_identity_record_context(frm);

									if (retry_result) {
										frm.__jpr_identity_context_restored =
											true;
									}
								}
							}, 300);
						} else {
							frm.__jpr_identity_context_restored = true;
						}
					}
				}, 300);
			}
		}
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
		format_name_field(
			frm,
			"surname_as_document"
		);
	},

	first_name_as_document(frm) {
		format_name_field(
			frm,
			"first_name_as_document"
		);
	},

	middle_names_as_document(frm) {
		format_name_field(
			frm,
			"middle_names_as_document"
		);
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
		NAME_FIELDS.forEach((fieldname) => {
			frm.doc[fieldname] =
				to_title_case(
					frm.doc[fieldname]
				);
		});

		set_full_name(frm);
		update_document_status(frm);
	},

	after_save(frm) {
		return_identity_record_to_release(frm);
	},
});

/*
 * ============================================================
 * RELEASE -> IDENTITY RECORD
 * ============================================================
 */

function restore_identity_record_context(frm) {
	console.log(
		"[IR] ===== RESTORE IDENTITY RECORD CONTEXT ====="
	);

	/*
	 * First try the sessionStorage context.
	 */
	let context =
		get_identity_record_context();

	/*
	 * If sessionStorage is not available yet, use the
	 * route options captured during onload.
	 */
	const route_options =
		frm.__jpr_route_options;

	if (!context && route_options) {
		console.log(
			"[IR] No sessionStorage context. Using captured route options."
		);

		context = {
			profile:
				route_options.profile || "",

			party_kind:
				route_options.party_kind || "",

			country:
				route_options.country || "",

			evidence_type:
				route_options.evidence_type || "",

			source_class:
				route_options.source_class ||
				"Certified Copy",

			document_type:
				route_options.document_type || "",

			doc_type:
				route_options.doc_type || "",

			tax_details:
				route_options.tax_details || "",

			issuing_jurisdiction:
				route_options.issuing_jurisdiction ||
				"",

			fact_key:
				route_options.fact_key || "",

			valid_from:
				route_options.valid_from || "",

			valid_to:
				route_options.valid_to || "",

			authoritative_source:
				route_options.authoritative_source ||
				"",

			source_reference:
				route_options.source_reference ||
				"",

			authority_level:
				route_options.authority_level || "",

			verification_method:
				route_options.verification_method ||
				"",

			verification_outcome:
				route_options.verification_outcome ||
				"",

			verified_on:
				route_options.verified_on || "",

			verified_by:
				route_options.verified_by || "",

			fresh_until:
				route_options.fresh_until || "",

			qualification:
				route_options.qualification || "",

			lifecycle_state:
				route_options.lifecycle_state || "",

			content_hash:
				route_options.content_hash || "",
		};
	}

	if (!context) {
		console.log(
			"[IR] No Release context found."
		);

		return false;
	}

	/*
	 * Only populate a newly created Identity Record.
	 */
	if (!frm.is_new()) {
		console.log(
			"[IR] Existing Identity Record. Context will not be restored."
		);

		return false;
	}

	console.log(
		"[IR] Context being applied:",
		context
	);

	/*
	 * ----------------------------------------------------------
	 * Parent Release values
	 * ----------------------------------------------------------
	 */

	set_if_field_exists(
		frm,
		"profile",
		context.profile
	);

	set_if_field_exists(
		frm,
		"party_kind",
		context.party_kind
	);

	set_if_field_exists(
		frm,
		"country",
		context.country
	);

	/*
	 * ----------------------------------------------------------
	 * Evidence information
	 * ----------------------------------------------------------
	 */

	set_if_field_exists(
		frm,
		"evidence_type",
		context.evidence_type
	);

	set_if_field_exists(
		frm,
		"source_class",
		context.source_class ||
			"Certified Copy"
	);

	/*
	 * ----------------------------------------------------------
	 * Requirement type
	 *
	 * Identifier Fact:
	 * requirement_type -> document_type
	 *
	 * Statutory Registration Fact:
	 * requirement_type -> doc_type
	 *
	 * Tax Obligation Fact:
	 * requirement_type -> tax_details
	 * ----------------------------------------------------------
	 */

	if (
		context.requirement_type &&
		context.requirement_field
	) {
		set_if_field_exists(
			frm,
			context.requirement_field,
			context.requirement_type
		);
	}

	/*
	 * When restoring from route_options, requirement
	 * fields are already mapped directly.
	 */
	if (context.document_type) {
		set_if_field_exists(
			frm,
			"document_type",
			context.document_type
		);
	}

	if (context.doc_type) {
		set_if_field_exists(
			frm,
			"doc_type",
			context.doc_type
		);
	}

	if (context.tax_details) {
		set_if_field_exists(
			frm,
			"tax_details",
			context.tax_details
		);
	}

	/*
	 * ----------------------------------------------------------
	 * Fields already known from the selected Fact.
	 * ----------------------------------------------------------
	 */

	const known_fields = [
		"issuing_jurisdiction",
		"fact_key",
		"valid_from",
		"valid_to",
		"source_class",
		"authoritative_source",
		"source_reference",
		"authority_level",
		"verification_method",
		"verification_outcome",
		"verified_on",
		"verified_by",
		"fresh_until",
		"qualification",
		"lifecycle_state",
		"content_hash",
	];

	known_fields.forEach(
		(fieldname) => {
			set_if_field_exists(
				frm,
				fieldname,
				context[fieldname]
			);
		}
	);

	/*
	 * ----------------------------------------------------------
	 * Refresh populated fields.
	 * ----------------------------------------------------------
	 */

	refresh_existing_fields(frm);

	configure_location_queries(frm);
	setup_date_restrictions(frm);
	update_location_field_states(frm);
	handle_has_expiry(frm);
	update_document_status(frm);
	set_full_name(frm);

	console.log(
		"[IR] Restored Identity Record values:",
		{
			profile:
				frm.doc.profile,

			party_kind:
				frm.doc.party_kind,

			country:
				frm.doc.country,

			evidence_type:
				frm.doc.evidence_type,

			document_type:
				frm.doc.document_type,

			doc_type:
				frm.doc.doc_type,

			tax_details:
				frm.doc.tax_details,

			issuing_jurisdiction:
				frm.doc.issuing_jurisdiction,

			fact_key:
				frm.doc.fact_key,

			source_class:
				frm.doc.source_class,

			authoritative_source:
				frm.doc.authoritative_source,

			source_reference:
				frm.doc.source_reference,

			authority_level:
				frm.doc.authority_level,

			verification_method:
				frm.doc.verification_method,

			verification_outcome:
				frm.doc.verification_outcome,

			verified_on:
				frm.doc.verified_on,

			verified_by:
				frm.doc.verified_by,

			fresh_until:
				frm.doc.fresh_until,

			qualification:
				frm.doc.qualification,

			lifecycle_state:
				frm.doc.lifecycle_state,

			content_hash:
				frm.doc.content_hash,
		}
	);

	return true;
}

function return_identity_record_to_release(frm) {
	const context =
		get_identity_record_context();

	if (!context) {
		return;
	}

	sessionStorage.setItem(
		IDENTITY_RECORD_CREATED_KEY,
		frm.doc.name
	);

	if (context.release_name) {
		frappe.set_route(
			"Form",
			"Jurisdiction Profile Release",
			context.release_name
		);
	}
}

function get_identity_record_context() {
	const raw_context =
		sessionStorage.getItem(
			IDENTITY_RECORD_CONTEXT_KEY
		);

	if (!raw_context) {
		return null;
	}

	try {
		return JSON.parse(raw_context);
	} catch (error) {
		console.error(
			"[IR] Unable to read Identity Record context:",
			error
		);

		sessionStorage.removeItem(
			IDENTITY_RECORD_CONTEXT_KEY
		);

		return null;
	}
}

/*
 * ============================================================
 * FIELD HELPERS
 * ============================================================
 */

function set_if_field_exists(
	frm,
	fieldname,
	value
) {
	if (
		!fieldname ||
		value === undefined ||
		value === null ||
		value === ""
	) {
		return;
	}

	if (!frm.fields_dict[fieldname]) {
		console.warn(
			"[IR] Field does not exist:",
			fieldname
		);

		return;
	}

	frm.set_value(
		fieldname,
		value
	);
}

function refresh_existing_fields(frm) {
	const fields_to_refresh = [
		"profile",
		"party_kind",
		"country",
		"evidence_type",
		"source_class",

		"document_type",
		"doc_type",
		"tax_details",

		"issuing_jurisdiction",
		"fact_key",
		"valid_from",
		"valid_to",
		"authoritative_source",
		"source_reference",
		"authority_level",
		"verification_method",
		"verification_outcome",
		"verified_on",
		"verified_by",
		"fresh_until",
		"qualification",
		"lifecycle_state",
		"content_hash",

		"document_number",
		"issuing_country",

		"first_name_as_document",
		"middle_names_as_document",
		"surname_as_document",
		"other_name_as_document",

		"date_of_birth",
		"gender_as_document",
		"nationality_as_document",
		"country_of_birth",

		"date_of_issue",
		"has_expiry",
		"date_of_expiry",

		"county",
		"constituency",
		"ward",
		"location",
		"sub_location",
	];

	fields_to_refresh.forEach(
		(fieldname) => {
			if (
				frm.fields_dict[fieldname]
			) {
				frm.refresh_field(
					fieldname
				);
			}
		}
	);
}

/*
 * ============================================================
 * LOCATION CASCADE
 * ============================================================
 */

function configure_location_queries(frm) {
	frm.set_query(
		"constituency",
		() => ({
			filters: {
				county:
					frm.doc.county,
			},
		})
	);

	frm.set_query(
		"ward",
		() => ({
			filters: {
				constituency:
					frm.doc.constituency,
			},
		})
	);

	frm.set_query(
		"location",
		() => ({
			filters: {
				ward:
					frm.doc.ward,
			},
		})
	);

	frm.set_query(
		"sub_location",
		() => ({
			filters: {
				location:
					frm.doc.location,
			},
		})
	);
}

function clear_fields(
	frm,
	fields
) {
	fields.forEach(
		(fieldname) => {
			if (
				frm.fields_dict[fieldname] &&
				frm.doc[fieldname]
			) {
				frm.set_value(
					fieldname,
					null
				);
			}
		}
	);
}

function update_location_field_states(
	frm
) {
	const dependencies = {
		constituency: "county",
		ward: "constituency",
		location: "ward",
		sub_location: "location",
	};

	Object.entries(
		dependencies
	).forEach(
		([fieldname, parent]) => {
			if (
				frm.fields_dict[fieldname]
			) {
				frm.toggle_enable(
					fieldname,
					Boolean(
						frm.doc[parent]
					)
				);
			}
		}
	);
}

/*
 * ============================================================
 * NAME FORMATTING
 * ============================================================
 */

function to_title_case(value) {
	if (!value) {
		return value;
	}

	return value
		.trim()
		.replace(/\s+/g, " ")
		.toLowerCase()
		.replace(
			/(^|[\s\\'’\-])(\p{L})/gu,
			(match, separator, letter) =>
				separator +
				letter.toUpperCase()
		);
}

function format_name_field(
	frm,
	fieldname
) {
	const current =
		frm.doc[fieldname];

	const formatted =
		to_title_case(current);

	if (
		formatted !== current
	) {
		frm.set_value(
			fieldname,
			formatted
		).then(() => {
			set_full_name(frm);
		});
	} else {
		set_full_name(frm);
	}
}

function set_full_name(frm) {
	if (
		!frm.fields_dict
			.full_name_as_document
	) {
		return;
	}

	const names = NAME_FIELDS
		.map((fieldname) =>
			to_title_case(
				frm.doc[fieldname]
			)
		)
		.filter(Boolean);

	frm.set_value(
		"full_name_as_document",
		names.join(" ")
	);
}

/*
 * ============================================================
 * DATE VALIDATION
 * ============================================================
 */

function setup_date_restrictions(frm) {
	const today =
		frappe.datetime.get_today();

	Object.entries(
		DATE_RULES
	).forEach(
		([fieldname, rule]) => {
			if (
				!frm.fields_dict[fieldname]
			) {
				return;
			}

			const properties = {
				max:
					rule.type === "past"
						? today
						: null,

				min:
					rule.type === "future"
						? today
						: null,
			};

			Object.entries(
				properties
			).forEach(
				([property, value]) => {
					frm.set_df_property(
						fieldname,
						property,
						value
					);
				}
			);
		}
	);
}

function validate_date(
	frm,
	fieldname
) {
	const value =
		frm.doc[fieldname];

	if (
		!value ||
		!DATE_RULES[fieldname]
	) {
		return;
	}

	const today =
		frappe.datetime.get_today();

	const rule =
		DATE_RULES[fieldname];

	if (
		rule.type === "past" &&
		value > today
	) {
		clear_invalid_date(
			frm,
			fieldname,
			"Date cannot be in the future."
		);

		return;
	}

	if (
		rule.type === "future" &&
		value < today
	) {
		clear_invalid_date(
			frm,
			fieldname,
			"Date cannot be in the past."
		);

		return;
	}

	validate_date_relationship(
		frm,
		fieldname
	);
}

function validate_date_relationship(
	frm,
	fieldname
) {
	const rule =
		DATE_RULES[fieldname];

	if (!rule.relationship) {
		return;
	}

	const [
		related_field,
		field_label,
		related_label,
	] = rule.relationship;

	const current_date =
		frm.doc[fieldname];

	const related_date =
		frm.doc[related_field];

	if (
		!current_date ||
		!related_date
	) {
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

function clear_invalid_date(
	frm,
	fieldname,
	message
) {
	frm.set_value(
		fieldname,
		null
	);

	frappe.msgprint({
		title: "Invalid Date",
		message,
		indicator: "red",
	});
}

/*
 * ============================================================
 * EXPIRY
 * ============================================================
 */

function handle_has_expiry(frm) {
	if (
		!frm.fields_dict.date_of_expiry
	) {
		return;
	}

	const has_expiry =
		frm.doc.has_expiry === "Yes";

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

	if (
		!has_expiry &&
		frm.doc.date_of_expiry
	) {
		frm.set_value(
			"date_of_expiry",
			null
		);
	}
}

/*
 * ============================================================
 * DOCUMENT STATUS
 * ============================================================
 */

function update_document_status(frm) {
	if (
		frm.doc.evidence_type !==
			"Identifier Facts" ||
		frm.doc.has_expiry !== "Yes" ||
		!frm.doc.date_of_expiry
	) {
		return;
	}

	const today =
		frappe.datetime.get_today();

	frm.set_value(
		"document_status",
		frm.doc.date_of_expiry <
			today
			? "Expired"
			: "Valid"
	);
}
