// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt

const IDENTITY_RECORD_CONTEXT_KEY =
	"jurisdiction_profile_release_identity_record_context";

const IDENTITY_RECORD_CREATED_KEY =
	"jurisdiction_profile_release_identity_record_created";


frappe.ui.form.on("Jurisdiction Profile Release", {
	onload(frm) {
		console.log(
			"[JPR] onload:",
			frm.doc.name,
			"new:",
			frm.is_new()
		);

		restore_release_after_identity_record(frm);
	},

	setup(frm) {
		console.log("[JPR] setup");

		frm.set_query(
			"identity_record",
			"identifier_facts",
			function () {
				return {
					filters: {
						evidence_type: "Identifier Facts",
					},
				};
			}
		);

		frm.set_query(
			"identity_record",
			"statutory_registration_facts",
			function () {
				return {
					filters: {
						evidence_type: "Statutory Registration Facts",
					},
				};
			}
		);

		frm.set_query(
			"identity_record",
			"tax_obligation_facts",
			function () {
				return {
					filters: {
						evidence_type: "Tax Details",
					},
				};
			}
		);

		frm.set_query(
			"jurisdiction_compliance_template",
			function () {
				if (!frm.doc.profile) {
					return {};
				}

				return {
					filters: {
						country: frm.doc.country,
						party_kind: frm.doc.party_kind,
					},
				};
			}
		);
	},

	profile(frm) {
		console.log("[JPR] profile changed:", frm.doc.profile);

		/*
		 * While we're rehydrating an unsaved Release from a stored
		 * Identity Record context, the stored child tables are the
		 * source of truth. Running the normal reset cascade here
		 * would clear/reload the template asynchronously and wipe
		 * out the child rows we're about to restore (including the
		 * identity_record link that triggered this whole flow).
		 */
		if (frm.__restoring_identity_record_context) {
			return;
		}

		frm.set_value("jurisdiction_compliance_template", "");

		clear_release_fact_tables(frm);
	},

	jurisdiction_compliance_template(frm) {
		console.log(
			"[JPR] template changed:",
			frm.doc.jurisdiction_compliance_template
		);

		if (frm.__restoring_identity_record_context) {
			return;
		}

		if (!frm.doc.jurisdiction_compliance_template) {
			clear_release_fact_tables(frm);
			return;
		}

		frappe.call({
			method: "frappe.client.get",
			args: {
				doctype: "Jurisdiction Compliance Template",
				name: frm.doc.jurisdiction_compliance_template,
			},
			callback(r) {
				if (!r.message) {
					console.warn(
						"[JPR] No template response."
					);
					return;
				}

				const template = r.message;

				console.log(
					"[JPR] template response:",
					template
				);

				clear_release_fact_tables(frm);

				/*
				 * IDENTIFIER FACTS
				 */
				(template.identifier_record || []).forEach(
					(requirement) => {
						const row = frm.add_child(
							"identifier_facts"
						);

						row.requirement_type =
							requirement.requirement_type;

						row.is_mandatory =
							requirement.is_mandatory;

						copy_if_present(
							requirement,
							row,
							"issuing_jurisdiction"
						);

						copy_if_present(
							requirement,
							row,
							"fact_key"
						);

						copy_if_present(
							requirement,
							row,
							"valid_from"
						);

						copy_if_present(
							requirement,
							row,
							"valid_to"
						);

						copy_if_present(
							requirement,
							row,
							"source_class"
						);

						copy_if_present(
							requirement,
							row,
							"authoritative_source"
						);

						copy_if_present(
							requirement,
							row,
							"source_reference"
						);

						copy_if_present(
							requirement,
							row,
							"authority_level"
						);

						copy_if_present(
							requirement,
							row,
							"verification_method"
						);

						copy_if_present(
							requirement,
							row,
							"verification_outcome"
						);

						copy_if_present(
							requirement,
							row,
							"verified_on"
						);

						copy_if_present(
							requirement,
							row,
							"verified_by"
						);

						copy_if_present(
							requirement,
							row,
							"fresh_until"
						);

						copy_if_present(
							requirement,
							row,
							"qualification"
						);

						copy_if_present(
							requirement,
							row,
							"lifecycle_state"
						);

						copy_if_present(
							requirement,
							row,
							"content_hash"
						);
					}
				);

				console.log(
					"[JPR] identifier facts after template load:",
					frm.doc.identifier_facts
				);

				/*
				 * STATUTORY REGISTRATION FACTS
				 */
				(
					template.statutory_registration_requirement ||
					[]
				).forEach((requirement) => {
					const row = frm.add_child(
						"statutory_registration_facts"
					);

					row.requirement_type =
						requirement.requirement_type;

					row.is_mandatory =
						requirement.is_mandatory;

					copy_if_present(
						requirement,
						row,
						"issuing_jurisdiction"
					);

					copy_if_present(
						requirement,
						row,
						"fact_key"
					);

					copy_if_present(
						requirement,
						row,
						"valid_from"
					);

					copy_if_present(
						requirement,
						row,
						"valid_to"
					);

					copy_if_present(
						requirement,
						row,
						"source_class"
					);

					copy_if_present(
						requirement,
						row,
						"authoritative_source"
					);

					copy_if_present(
						requirement,
						row,
						"source_reference"
					);

					copy_if_present(
						requirement,
						row,
						"authority_level"
					);

					copy_if_present(
						requirement,
						row,
						"verification_method"
					);

					copy_if_present(
						requirement,
						row,
						"verification_outcome"
					);

					copy_if_present(
						requirement,
						row,
						"verified_on"
					);

					copy_if_present(
						requirement,
						row,
						"verified_by"
					);

					copy_if_present(
						requirement,
						row,
						"fresh_until"
					);

					copy_if_present(
						requirement,
						row,
						"qualification"
					);

					copy_if_present(
						requirement,
						row,
						"lifecycle_state"
					);

					copy_if_present(
						requirement,
						row,
						"content_hash"
					);
				});

				console.log(
					"[JPR] statutory facts after template load:",
					frm.doc.statutory_registration_facts
				);

				/*
				 * TAX OBLIGATION FACTS
				 */
				(template.tax_details || []).forEach(
					(requirement) => {
						const row = frm.add_child(
							"tax_obligation_facts"
						);

						row.requirement_type =
							requirement.requirement_type;

						row.is_mandatory =
							requirement.is_mandatory;

						copy_if_present(
							requirement,
							row,
							"issuing_jurisdiction"
						);

						copy_if_present(
							requirement,
							row,
							"fact_key"
						);

						copy_if_present(
							requirement,
							row,
							"valid_from"
						);

						copy_if_present(
							requirement,
							row,
							"valid_to"
						);

						copy_if_present(
							requirement,
							row,
							"source_class"
						);

						copy_if_present(
							requirement,
							row,
							"authoritative_source"
						);

						copy_if_present(
							requirement,
							row,
							"source_reference"
						);

						copy_if_present(
							requirement,
							row,
							"authority_level"
						);

						copy_if_present(
							requirement,
							row,
							"verification_method"
						);

						copy_if_present(
							requirement,
							row,
							"verification_outcome"
						);

						copy_if_present(
							requirement,
							row,
							"verified_on"
						);

						copy_if_present(
							requirement,
							row,
							"verified_by"
						);

						copy_if_present(
							requirement,
							row,
							"fresh_until"
						);

						copy_if_present(
							requirement,
							row,
							"qualification"
						);

						copy_if_present(
							requirement,
							row,
							"lifecycle_state"
						);

						copy_if_present(
							requirement,
							row,
							"content_hash"
						);
					}
				);

				console.log(
					"[JPR] tax facts after template load:",
					frm.doc.tax_obligation_facts
				);

				/*
				 * IMPORTANT:
				 * The standard Frappe Link field action
				 * "Create a new Identity Record" is hooked
				 * here after the grid rows exist.
				 */
				setup_identity_record_create_handlers(frm);

				frm.refresh_field("identifier_facts");
				frm.refresh_field(
					"statutory_registration_facts"
				);
				frm.refresh_field(
					"tax_obligation_facts"
				);

				/*
				 * Refresh again after the grid has rendered,
				 * because Frappe can recreate grid controls.
				 */
				setTimeout(() => {
					setup_identity_record_create_handlers(frm);
				}, 100);
			},
		});
	},

	refresh(frm) {
		setup_identity_record_create_handlers(frm);
	},
});


/*
 * ============================================================
 * STANDARD LINK FIELD "CREATE A NEW" HANDLER
 * ============================================================
 */

function setup_identity_record_create_handlers(frm) {
	const tables = [
		{
			fieldname: "identifier_facts",
			evidence_type: "Identifier Facts",
			requirement_field: "document_type",
		},
		{
			fieldname: "statutory_registration_facts",
			evidence_type: "Statutory Registration Facts",
			requirement_field: "doc_type",
		},
		{
			fieldname: "tax_obligation_facts",
			evidence_type: "Tax Details",
			requirement_field: "tax_details",
		},
	];

	tables.forEach((config) => {
		const table = frm.fields_dict[config.fieldname];

		if (!table || !table.grid) {
			return;
		}

		table.grid.grid_rows.forEach((grid_row) => {
			const field =
				grid_row.on_grid_fields_dict.identity_record;

			if (!field) {
				return;
			}

			if (field.__jpr_new_doc_hooked) {
				return;
			}

			field.__jpr_new_doc_hooked = true;

			console.log(
				"[JPR] Hooking identity_record.new_doc:",
				config.fieldname,
				grid_row.doc.name
			);

			field.new_doc = function () {
				console.log(
					"[JPR] ===== CREATE IDENTITY RECORD CLICKED ====="
				);

				console.log(
					"[JPR] Table:",
					config.fieldname
				);

				console.log(
					"[JPR] Child row:",
					grid_row.doc
				);

				open_identity_record_from_release(
					frm,
					grid_row.doc,
					config.evidence_type,
					config.requirement_field,
					config.fieldname
				);

				// IMPORTANT:
				// Do NOT call the original field.new_doc().
				// Frappe's default action would open a blank
				// Identity Record before our custom values
				// are applied.
			};
		});
	});
}

/*
 * ============================================================
 * OPEN IDENTITY RECORD FROM UNSAVED RELEASE
 * ============================================================
 */

function open_identity_record_from_release(
	frm,
	row,
	evidence_type,
	requirement_field,
	child_table_fieldname
) {
	console.log(
		"[JPR] ===== OPEN IDENTITY RECORD ====="
	);

	console.log(
		"[JPR] Release:",
		frm.doc.name
	);

	console.log(
		"[JPR] Child row:",
		row
	);

	console.log(
		"[JPR] Evidence type:",
		evidence_type
	);

	/*
	 * ----------------------------------------------------------
	 * Build complete context.
	 * ----------------------------------------------------------
	 */

	const context = {
		release_name: frm.doc.name,

		child_table_fieldname:
			child_table_fieldname,

		child_doctype:
			row.doctype,

		child_row_name:
			row.name,

		child_row_idx:
			row.idx,

		evidence_type,

		requirement_field,

		requirement_type:
			row.requirement_type || "",

		profile:
			frm.doc.profile || "",

		party_kind:
			frm.doc.party_kind || "",

		country:
			frm.doc.country || "",

		jurisdiction_compliance_template:
			frm.doc
				.jurisdiction_compliance_template ||
			"",

		is_mandatory:
			row.is_mandatory || "",

		issuing_jurisdiction:
			row.issuing_jurisdiction || "",

		fact_key:
			row.fact_key || "",

		valid_from:
			row.valid_from || "",

		valid_to:
			row.valid_to || "",

		source_class:
			row.source_class || "",

		authoritative_source:
			row.authoritative_source || "",

		source_reference:
			row.source_reference || "",

		authority_level:
			row.authority_level || "",

		verification_method:
			row.verification_method || "",

		verification_outcome:
			row.verification_outcome || "",

		verified_on:
			row.verified_on || "",

		verified_by:
			row.verified_by || "",

		fresh_until:
			row.fresh_until || "",

		qualification:
			row.qualification || "",

		lifecycle_state:
			row.lifecycle_state || "",

		content_hash:
			row.content_hash || "",

		identifier_facts:
			frm.doc.identifier_facts || [],

		statutory_registration_facts:
			frm.doc
				.statutory_registration_facts || [],

		tax_obligation_facts:
			frm.doc.tax_obligation_facts || [],

		compliance_entitlement_facts:
			frm.doc
				.compliance_entitlement_facts || [],
	};

	console.log(
		"[JPR] Identity Record context:",
		context
	);

	/*
	 * ----------------------------------------------------------
	 * Store context BEFORE opening the new document.
	 *
	 * This remains the source of truth for returning to the
	 * unsaved Release.
	 * ----------------------------------------------------------
	 */

	sessionStorage.setItem(
		IDENTITY_RECORD_CONTEXT_KEY,
		JSON.stringify(context)
	);

	console.log(
		"[JPR] Context stored in sessionStorage:",
		sessionStorage.getItem(
			IDENTITY_RECORD_CONTEXT_KEY
		)
	);

	/*
	 * ----------------------------------------------------------
	 * Build values for the new Identity Record.
	 *
	 * These are passed directly to frappe.new_doc().
	 * ----------------------------------------------------------
	 */

	const new_identity_record_values = {
		profile:
			context.profile,

		party_kind:
			context.party_kind,

		country:
			context.country,

		evidence_type:
			context.evidence_type,

		source_class:
			context.source_class ||
			"Certified Copy",
	};

	/*
	 * Requirement type mapping:
	 *
	 * Identifier Fact:
	 * requirement_type -> document_type
	 *
	 * Statutory Registration Fact:
	 * requirement_type -> doc_type
	 *
	 * Tax Obligation Fact:
	 * requirement_type -> tax_details
	 */

	if (
		context.requirement_type &&
		context.requirement_field
	) {
		new_identity_record_values[
			context.requirement_field
		] =
			context.requirement_type;
	}

	/*
	 * ----------------------------------------------------------
	 * Carry every already-known field into the new document.
	 * ----------------------------------------------------------
	 */

	const known_identity_fields = [
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

	known_identity_fields.forEach(
		(fieldname) => {
			if (
				context[fieldname] !==
					undefined &&
				context[fieldname] !== null &&
				context[fieldname] !== ""
			) {
				new_identity_record_values[
					fieldname
				] =
					context[fieldname];
			}
		}
	);

	console.log(
		"[JPR] New Identity Record values:",
		new_identity_record_values
	);

	/*
	 * ----------------------------------------------------------
	 * IMPORTANT:
	 *
	 * Use frappe.new_doc() instead of manually assigning
	 * frappe.route_options and calling frappe.set_route().
	 *
	 * This allows Frappe's new-document lifecycle to receive
	 * the values directly when creating the document.
	 * ----------------------------------------------------------
	 */

	frappe.new_doc(
		"Identity Record",
		new_identity_record_values
	);
}


/*
 * ============================================================
 * RESTORE RELEASE AFTER IDENTITY RECORD CREATION
 * ============================================================
 */

function restore_release_after_identity_record(frm) {
	console.log(
		"[JPR] ===== RESTORE RELEASE ====="
	);

	const raw_context =
		sessionStorage.getItem(
			IDENTITY_RECORD_CONTEXT_KEY
		);

	const created_identity_record =
		sessionStorage.getItem(
			IDENTITY_RECORD_CREATED_KEY
		);

	console.log(
		"[JPR] Stored Release context:",
		raw_context
	);

	console.log(
		"[JPR] Created Identity Record:",
		created_identity_record
	);

	if (!raw_context) {
		console.log(
			"[JPR] No stored context. Nothing to restore."
		);

		return;
	}

	/*
	 * This restore only ever applies to a freshly opened, unsaved
	 * Release form (the one recreated after routing back from the
	 * Identity Record detour). A saved/existing Release should
	 * never be silently overwritten with stored context.
	 *
	 * Note: we deliberately do NOT compare frm.doc.name against
	 * context.release_name here. Frappe regenerates a new
	 * "new-jurisdiction-profile-release-*" name every time a
	 * fresh form is opened, so that name is never stable across
	 * the route-away/route-back detour and is not a reliable
	 * match key.
	 */
	if (!frm.is_new()) {
		console.log(
			"[JPR] Current form is not new. Discarding stored context."
		);

		sessionStorage.removeItem(
			IDENTITY_RECORD_CONTEXT_KEY
		);

		sessionStorage.removeItem(
			IDENTITY_RECORD_CREATED_KEY
		);

		return;
	}

	let context;

	try {
		context = JSON.parse(raw_context);
	} catch (error) {
		console.error(
			"[JPR] Could not parse stored context:",
			error
		);

		sessionStorage.removeItem(
			IDENTITY_RECORD_CONTEXT_KEY
		);

		return;
	}

	console.log(
		"[JPR] Restoring Release context:",
		context
	);

	/*
	 * Suppress the profile/template change cascade for the
	 * duration of the restore. Without this, frm.set_value(
	 * "profile", ...) below triggers the normal profile(frm)
	 * handler, which clears the fact tables and (via the
	 * jurisdiction_compliance_template default/fetch) kicks off
	 * an async template reload. That reload finishes AFTER the
	 * child tables below have already been restored, and clears
	 * + rebuilds them from the template again — silently
	 * discarding the restored rows and the identity_record link
	 * we are about to set.
	 */
	frm.__restoring_identity_record_context = true;

	try {
		/*
		 * Restore the parent fields.
		 */
		if (context.profile) {
			frm.set_value(
				"profile",
				context.profile
			);
		}

		if (context.party_kind) {
			frm.set_value(
				"party_kind",
				context.party_kind
			);
		}

		if (context.country) {
			frm.set_value(
				"country",
				context.country
			);
		}

		if (context.jurisdiction_compliance_template) {
			frm.set_value(
				"jurisdiction_compliance_template",
				context.jurisdiction_compliance_template
			);
		}

		/*
		 * Restore all child tables.
		 */
		restore_child_table(
			frm,
			"identifier_facts",
			context.identifier_facts
		);

		restore_child_table(
			frm,
			"statutory_registration_facts",
			context.statutory_registration_facts
		);

		restore_child_table(
			frm,
			"tax_obligation_facts",
			context.tax_obligation_facts
		);

		restore_child_table(
			frm,
			"compliance_entitlement_facts",
			context.compliance_entitlement_facts
		);

		/*
		 * Restore the Identity Record link only after the
		 * child rows have been recreated.
		 *
		 * We use idx instead of child_row_name because
		 * Frappe generates a new local name when frm.add_child()
		 * recreates an unsaved row.
		 */
		if (created_identity_record) {
			let target_row = null;

			const rows =
				frm.doc[context.child_table_fieldname] || [];

			if (context.child_row_idx !== undefined) {
				target_row = rows.find(
					(row) => row.idx === context.child_row_idx
				);
			}

			if (!target_row && context.requirement_type) {
				target_row = rows.find(
					(row) =>
						row.requirement_type ===
						context.requirement_type
				);
			}

			if (!target_row) {
				console.warn(
					"[JPR] Could not find target child row:",
					context
				);
			} else {
				target_row.identity_record =
					created_identity_record;

				frm.refresh_field(
					context.child_table_fieldname
				);
			}
		}
	} finally {
		/*
		 * Always re-enable the normal cascade, even if something
		 * above throws, so the form isn't left in a state where
		 * legitimate future profile/template changes are ignored.
		 */
		frm.__restoring_identity_record_context = false;
	}

	/*
	 * Reinstall the standard Link-field Create handler
	 * after rebuilding the grids.
	 */
	setTimeout(() => {
		setup_identity_record_create_handlers(frm);
	}, 100);

	/*
	 * Context has now been consumed.
	 */
	sessionStorage.removeItem(
		IDENTITY_RECORD_CONTEXT_KEY
	);

	sessionStorage.removeItem(
		IDENTITY_RECORD_CREATED_KEY
	);
}


/*
 * ============================================================
 * RESTORE CHILD TABLE
 * ============================================================
 */

function restore_child_table(
	frm,
	fieldname,
	rows
) {
	if (!frm.fields_dict[fieldname]) {
		return;
	}

	if (!Array.isArray(rows)) {
		return;
	}

	frm.clear_table(fieldname);

	rows.forEach((stored_row) => {
		const row = frm.add_child(
			fieldname
		);

		Object.keys(stored_row).forEach(
			(key) => {
				if (
					key === "name" ||
					key === "doctype" ||
					key === "parent" ||
					key === "parentfield" ||
					key === "parenttype" ||
					key === "owner" ||
					key === "creation" ||
					key === "modified" ||
					key === "modified_by"
				) {
					return;
				}

				if (
					stored_row[key] !==
						undefined &&
					stored_row[key] !== null
				) {
					row[key] =
						stored_row[key];
				}
			}
		);
	});

	frm.refresh_field(fieldname);
}


/*
 * ============================================================
 * HELPERS
 * ============================================================
 */

function copy_if_present(
	source,
	target,
	fieldname
) {
	if (
		source[fieldname] !==
			undefined &&
		source[fieldname] !== null &&
		source[fieldname] !== ""
	) {
		target[fieldname] =
			source[fieldname];
	}
}


function clear_release_fact_tables(frm) {
	console.log(
		"[JPR] Clearing release fact tables."
	);

	[
		"identifier_facts",
		"statutory_registration_facts",
		"tax_obligation_facts",
		"compliance_entitlement_facts",
	].forEach((fieldname) => {
		if (frm.fields_dict[fieldname]) {
			frm.clear_table(fieldname);
			frm.refresh_field(fieldname);
		}
	});
}