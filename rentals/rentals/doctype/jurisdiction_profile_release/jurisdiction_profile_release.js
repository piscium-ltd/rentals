// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt


const IDENTITY_RECORD_CONTEXT_KEY =
	"jurisdiction_profile_release_identity_record_context";

const IDENTITY_RECORD_CREATED_KEY =
	"jurisdiction_profile_release_identity_record_created";

const IDENTITY_RECORD_LINK_FIELD =
	"identity_record";

const IDENTITY_RECORD_DOCTYPE =
	"Identity Record";

const JURISDICTION_PROFILE_RELEASE_DOCTYPE =
	"Jurisdiction Profile Release";


// -----------------------------------------------------------------------------
// FORM EVENTS
// -----------------------------------------------------------------------------

frappe.ui.form.on(
	"Jurisdiction Profile Release",
	{
		onload(frm) {
			console.log(
				"[JPR] onload:",
				frm.doc.name,
				"new:",
				frm.is_new() ? 1 : 0
			);

			restore_release_after_identity_record(frm);
		},

		setup(frm) {
			console.log(
				"[JPR] setup"
			);

			setup_identity_record_create_handler();

			configure_identity_record_queries(
				frm
			);

			configure_template_query(
				frm
			);
		},

		profile(frm) {
			if (
				frm.__restoring_identity_record_context
			) {
				console.log(
					"[JPR] profile changed: ignored during restore"
				);

				return;
			}

			console.log(
				"[JPR] profile changed:",
				frm.doc.profile
			);

			clear_release_fact_tables(
				frm
			);
		},

		jurisdiction_compliance_template(frm) {
			if (
				frm.__restoring_identity_record_context
			) {
				console.log(
					"[JPR] template changed: ignored during restore"
				);

				return;
			}

			console.log(
				"[JPR] template changed:",
				frm.doc.jurisdiction_compliance_template
			);

			if (
				!frm.doc
					.jurisdiction_compliance_template
			) {
				clear_release_fact_tables(
					frm
				);

				return;
			}

			load_template_requirements(
				frm
			);
		},

		refresh(frm) {
			console.log(
				"[JPR] refresh:",
				frm.doc.name,
				"new:",
				frm.is_new() ? 1 : 0
			);

			setup_identity_record_create_handler();

			configure_identity_record_queries(
				frm
			);

			configure_template_query(
				frm
			);

			/*
			 * Frappe can reuse the existing unsaved
			 * Release form when returning from
			 * Identity Record.
			 *
			 * Therefore restoration is attempted
			 * from refresh as well as onload.
			 */
			restore_release_after_identity_record(
				frm
			);
		},
	}
);


// -----------------------------------------------------------------------------
// IDENTITY RECORD CREATE HANDLER
// -----------------------------------------------------------------------------
//
// Frappe v16's ControlLink uses:
//
//     action: this.new_doc
//
// for the "Create a new ..." option.
//
// We intercept ControlLink.new_doc() before Frappe creates its normal blank
// document.
//
// The interception only applies to:
//
//     Jurisdiction Profile Release
//         -> identity_record
//         -> Identity Record
//
// All other Link fields continue using normal Frappe behaviour.
// -----------------------------------------------------------------------------

function setup_identity_record_create_handler() {
	if (
		frappe.ui.form.ControlLink.prototype
			.__jpr_identity_record_new_doc_patched
	) {
		return;
	}

	const original_new_doc =
		frappe.ui.form.ControlLink.prototype
			.new_doc;

	frappe.ui.form.ControlLink.prototype.new_doc =
		function () {
			const field = this;

			const is_identity_record_link =
				field &&
				field.get_options &&
				field.get_options() ===
					IDENTITY_RECORD_DOCTYPE &&
				field.df &&
				field.df.fieldname ===
					IDENTITY_RECORD_LINK_FIELD &&
				field.frm &&
				field.frm.doctype ===
					JURISDICTION_PROFILE_RELEASE_DOCTYPE;

			if (
				!is_identity_record_link
			) {
				return original_new_doc.apply(
					this,
					arguments
				);
			}

			console.log(
				"[JPR] ===== CREATE IDENTITY RECORD INTERCEPTED ====="
			);

			const frm =
				field.frm;

			const row =
				field.doc;

			if (!row) {
				console.error(
					"[JPR] Could not determine child row for identity_record."
				);

				return original_new_doc.apply(
					this,
					arguments
				);
			}

			const child_table_fieldname =
				row.parentfield;

			if (
				!child_table_fieldname
			) {
				console.error(
					"[JPR] Child row has no parentfield.",
					row
				);

				return original_new_doc.apply(
					this,
					arguments
				);
			}

			const evidence_type =
				get_identity_record_evidence_type(
					child_table_fieldname
				);

			const requirement_field =
				get_identity_record_requirement_field(
					child_table_fieldname
				);

			console.log(
				"[JPR] Table:",
				child_table_fieldname
			);

			console.log(
				"[JPR] Child row:",
				row
			);

			console.log(
				"[JPR] Evidence type:",
				evidence_type
			);

			open_identity_record_from_release(
				frm,
				row,
				evidence_type,
				requirement_field,
				child_table_fieldname
			);

			/*
			 * Do NOT call original_new_doc().
			 *
			 * Calling it would create Frappe's normal
			 * blank Identity Record.
			 */
			return false;
		};

	frappe.ui.form.ControlLink.prototype
		.__jpr_identity_record_new_doc_patched =
		true;

	console.log(
		"[JPR] ControlLink.new_doc() patched for Identity Record."
	);
}


// -----------------------------------------------------------------------------
// DETERMINE EVIDENCE TYPE
// -----------------------------------------------------------------------------

function get_identity_record_evidence_type(
	child_table_fieldname
) {
	switch (
		child_table_fieldname
	) {
		case "identifier_facts":
			return "Identifier Facts";

		case "statutory_registration_facts":
			return "Statutory Registration Facts";

		case "tax_obligation_facts":
			return "Tax Details";

		default:
			return "";
	}
}


// -----------------------------------------------------------------------------
// DETERMINE REQUIREMENT FIELD
// -----------------------------------------------------------------------------

function get_identity_record_requirement_field(
	child_table_fieldname
) {
	switch (
		child_table_fieldname
	) {
		case "identifier_facts":
			return "document_type";

		case "statutory_registration_facts":
			return "doc_type";

		case "tax_obligation_facts":
			return "tax_details";

		default:
			return "";
	}
}


// -----------------------------------------------------------------------------
// OPEN PREFILLED IDENTITY RECORD
// -----------------------------------------------------------------------------

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


	// -------------------------------------------------------------------------
	// STORE EVERYTHING REQUIRED TO RESTORE THE UNSAVED RELEASE
	// -------------------------------------------------------------------------

	const context = {
		release_name:
			frm.doc.name,

		child_table_fieldname:
			child_table_fieldname,

		child_doctype:
			row.doctype,

		child_row_name:
			row.name,

		child_row_idx:
			row.idx,

		evidence_type:
			evidence_type,

		requirement_field:
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

		identifier_facts:
			frm.doc.identifier_facts || [],

		statutory_registration_facts:
			frm.doc
				.statutory_registration_facts ||
			[],

		tax_obligation_facts:
			frm.doc.tax_obligation_facts || [],

		compliance_entitlement_facts:
			frm.doc
				.compliance_entitlement_facts ||
			[],
	};

	console.log(
		"[JPR] Release restoration context:",
		context
	);


	sessionStorage.setItem(
		IDENTITY_RECORD_CONTEXT_KEY,
		JSON.stringify(context)
	);


	/*
	 * Always remove an old created-record marker
	 * before starting a new Identity Record flow.
	 */
	sessionStorage.removeItem(
		IDENTITY_RECORD_CREATED_KEY
	);

	console.log(
		"[JPR] Context stored:",
		JSON.stringify(context)
	);


	// -------------------------------------------------------------------------
	// ONLY THESE VALUES ARE COPIED TO IDENTITY RECORD
	// -------------------------------------------------------------------------

	const values = {
		profile:
			frm.doc.profile || "",

		party_kind:
			frm.doc.party_kind || "",

		country:
			frm.doc.country || "",

		evidence_type:
			evidence_type || "",

		source_class:
			row.source_class ||
			"Certified Copy",

		document_type:
			"",

		doc_type:
			"",

		tax_details:
			"",
	};


	// -------------------------------------------------------------------------
	// COPY REQUIREMENT TYPE INTO CORRECT IDENTITY RECORD FIELD
	// -------------------------------------------------------------------------

	if (
		row.requirement_type &&
		requirement_field
	) {
		values[
			requirement_field
		] =
			row.requirement_type;
	}


	console.log(
		"[JPR] Identity Record values before creation:",
		values
	);


	// -------------------------------------------------------------------------
	// CREATE LOCAL IDENTITY RECORD FIRST
	// -------------------------------------------------------------------------

	frappe.model.with_doctype(
		IDENTITY_RECORD_DOCTYPE,
		() => {
			console.log(
				"[JPR] Identity Record DocType loaded."
			);

			const identity_record =
				frappe.model.get_new_doc(
					IDENTITY_RECORD_DOCTYPE
				);


			Object.keys(
				values
			).forEach(
				(fieldname) => {
					if (
						Object.prototype.hasOwnProperty.call(
							values,
							fieldname
						)
					) {
						identity_record[
							fieldname
						] =
							values[
								fieldname
							];
					}
				}
			);


			console.log(
				"[JPR] New Identity Record created in memory:",
				identity_record
			);

			console.log(
				"[JPR] Routing to prefilled Identity Record:",
				identity_record.name
			);


			frappe.set_route(
				"Form",
				IDENTITY_RECORD_DOCTYPE,
				identity_record.name
			);
		}
	);
}


// -----------------------------------------------------------------------------
// RESTORE RELEASE AFTER IDENTITY RECORD SAVE
// -----------------------------------------------------------------------------

function restore_release_after_identity_record(
	frm
) {
	console.log(
		"[JPR] ===== CHECK IDENTITY RECORD RESTORE ====="
	);


	if (
		frm.__identity_record_restore_running
	) {
		console.log(
			"[JPR] Restore already running. Skipping."
		);

		return;
	}


	const stored_context =
		sessionStorage.getItem(
			IDENTITY_RECORD_CONTEXT_KEY
		);

	const created_identity_record =
		sessionStorage.getItem(
			IDENTITY_RECORD_CREATED_KEY
		);


	console.log(
		"[JPR] Stored context exists:",
		!!stored_context
	);

	console.log(
		"[JPR] Created Identity Record:",
		created_identity_record
	);


	if (
		!stored_context ||
		!created_identity_record
	) {
		console.log(
			"[JPR] Nothing to restore."
		);

		return;
	}


	/*
	 * Only restore the unsaved Release.
	 */
	if (
		!frm.is_new()
	) {
		console.log(
			"[JPR] JPR is not new. Skipping restore:",
			frm.doc.name
		);

		return;
	}


	let context;


	try {
		context =
			JSON.parse(
				stored_context
			);
	} catch (error) {
		console.error(
			"[JPR] Failed to parse restore context:",
			error
		);

		clear_identity_record_restore_storage();

		return;
	}


	console.log(
		"[JPR] ===== RESTORING RELEASE ====="
	);

	console.log(
		"[JPR] Release:",
		context.release_name
	);

	console.log(
		"[JPR] Child table:",
		context.child_table_fieldname
	);

	console.log(
		"[JPR] Original child row:",
		context.child_row_name
	);

	console.log(
		"[JPR] Original child row idx:",
		context.child_row_idx
	);

	console.log(
		"[JPR] Identity Record to link:",
		created_identity_record
	);


	/*
	 * Prevent duplicate restore calls from
	 * onload + refresh.
	 */
	frm.__identity_record_restore_running =
		true;


	/*
	 * Prevent profile/template handlers from
	 * clearing restored child tables.
	 */
	frm.__restoring_identity_record_context =
		true;


	// -------------------------------------------------------------------------
	// RESTORE PARENT FIELDS
	// -------------------------------------------------------------------------

	if (
		context.profile
	) {
		frm.doc.profile =
			context.profile;
	}

	if (
		context.party_kind
	) {
		frm.doc.party_kind =
			context.party_kind;
	}

	if (
		context.country
	) {
		frm.doc.country =
			context.country;
	}

	if (
		context.jurisdiction_compliance_template
	) {
		frm.doc
			.jurisdiction_compliance_template =
			context
				.jurisdiction_compliance_template;
	}


	// -------------------------------------------------------------------------
	// RESTORE CHILD TABLES
	// -------------------------------------------------------------------------

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


	// -------------------------------------------------------------------------
	// FIND THE NEW RESTORED CHILD ROW
	// -------------------------------------------------------------------------

	const rows =
		frm.doc[
			context.child_table_fieldname
		] || [];


	console.log(
		"[JPR] Restored rows:",
		rows
	);


	let target_row =
		null;


	/*
	 * First try the original idx.
	 */
	if (
		context.child_row_idx
	) {
		target_row =
			rows.find(
				(row) =>
					Number(
						row.idx
					) ===
					Number(
						context.child_row_idx
					)
			);
	}


	/*
	 * Fallback to requirement_type.
	 */
	if (
		!target_row &&
		context.requirement_type
	) {
		target_row =
			rows.find(
				(row) =>
					row.requirement_type ===
					context.requirement_type
			);
	}


	if (
		!target_row
	) {
		console.error(
			"[JPR] FAILED: Could not find restored child row."
		);

		console.error(
			"[JPR] Table:",
			context.child_table_fieldname
		);

		console.error(
			"[JPR] Stored idx:",
			context.child_row_idx
		);

		console.error(
			"[JPR] Requirement type:",
			context.requirement_type
		);

		console.error(
			"[JPR] Rows:",
			rows
		);


		frm.__restoring_identity_record_context =
			false;

		frm.__identity_record_restore_running =
			false;

		return;
	}


	console.log(
		"[JPR] Restored target row:",
		target_row
	);


	// -------------------------------------------------------------------------
	// WRITE IDENTITY RECORD TO RESTORED ROW
	// -------------------------------------------------------------------------

	console.log(
		"[JPR] Writing Identity Record:",
		created_identity_record
	);

	console.log(
		"[JPR] Into child row:",
		target_row.name
	);


	/*
	 * Directly write the actual saved Identity Record
	 * into the NEW restored child-row object.
	 */
	target_row.identity_record =
		created_identity_record;

	target_row.__unsaved =
		1;


	/*
	 * Also use Frappe's model setter.
	 *
	 * The direct assignment above is intentional:
	 * the restored row is a newly-created local
	 * child row and its name is different from
	 * the original row.
	 */
	if (
		frappe.model &&
		frappe.model.set_value
	) {
		frappe.model.set_value(
			target_row.doctype,
			target_row.name,
			IDENTITY_RECORD_LINK_FIELD,
			created_identity_record
		);
	}


	// -------------------------------------------------------------------------
	// MARK RELEASE DIRTY
	// -------------------------------------------------------------------------

	frm.dirty();


	// -------------------------------------------------------------------------
	// REFRESH CHILD TABLE
	// -------------------------------------------------------------------------

	frm.refresh_field(
		context.child_table_fieldname
	);


	// -------------------------------------------------------------------------
	// FIRST VERIFICATION
	// -------------------------------------------------------------------------

	let current_rows =
		frm.doc[
			context.child_table_fieldname
		] || [];


	let current_target =
		current_rows.find(
			(row) =>
				row.name ===
				target_row.name
		);


	console.log(
		"[JPR] ===== FIRST LINK VERIFICATION ====="
	);

	console.log(
		"[JPR] Expected:",
		created_identity_record
	);

	console.log(
		"[JPR] Actual:",
		current_target
			? current_target.identity_record
			: null
	);


	// -------------------------------------------------------------------------
	// FINAL VERIFICATION AFTER GRID REFRESH
	// -----------------------------------------------------------------------------
	//
	// Frappe can rebuild the grid during refresh.
	// Therefore perform one final lookup and write.
	//

	setTimeout(
		() => {
			console.log(
				"[JPR] ===== FINAL IDENTITY RECORD LINK ====="
			);


			const latest_rows =
				frm.doc[
					context.child_table_fieldname
				] || [];


			let latest_target =
				latest_rows.find(
					(row) =>
						row.name ===
						target_row.name
				);


			/*
			 * If the row received a different local name,
			 * locate it again by idx.
			 */
			if (
				!latest_target &&
				context.child_row_idx
			) {
				latest_target =
					latest_rows.find(
						(row) =>
							Number(
								row.idx
							) ===
							Number(
								context.child_row_idx
							)
					);
			}


			/*
			 * Final fallback by requirement_type.
			 */
			if (
				!latest_target &&
				context.requirement_type
			) {
				latest_target =
					latest_rows.find(
						(row) =>
							row.requirement_type ===
							context.requirement_type
					);
			}


			if (
				!latest_target
			) {
				console.error(
					"[JPR] FINAL FAILURE: Target row disappeared."
				);

				console.error(
					"[JPR] Latest rows:",
					latest_rows
				);


				frm.__restoring_identity_record_context =
					false;

				frm.__identity_record_restore_running =
					false;

				return;
			}


			console.log(
				"[JPR] Final target row:",
				latest_target
			);


			// -----------------------------------------------------------------
			// FORCE FINAL IDENTITY RECORD VALUE
			// -----------------------------------------------------------------

			latest_target.identity_record =
				created_identity_record;

			latest_target.__unsaved =
				1;


			// -----------------------------------------------------------------
			// MARK RELEASE DIRTY
			// -----------------------------------------------------------------

			frm.dirty();


			// -----------------------------------------------------------------
			// REFRESH THE GRID
			// -----------------------------------------------------------------

			frm.refresh_field(
				context.child_table_fieldname
			);


			// -----------------------------------------------------------------
			// FINAL MODEL VERIFICATION
			// -----------------------------------------------------------------

			const verified_rows =
				frm.doc[
					context.child_table_fieldname
				] || [];


			let verified_target =
				verified_rows.find(
					(row) =>
						Number(
							row.idx
						) ===
						Number(
							context.child_row_idx
						)
				);


			/*
			 * Fallback by requirement_type.
			 */
			if (
				!verified_target &&
				context.requirement_type
			) {
				verified_target =
					verified_rows.find(
						(row) =>
							row.requirement_type ===
							context.requirement_type
					);
			}


			console.log(
				"[JPR] ===== FINAL VERIFICATION RESULT ====="
			);

			console.log(
				"[JPR] Expected Identity Record:",
				created_identity_record
			);

			console.log(
				"[JPR] Final child row:",
				verified_target
			);

			console.log(
				"[JPR] Actual Identity Record:",
				verified_target
					? verified_target.identity_record
					: null
			);


			// -----------------------------------------------------------------
			// SUCCESS
			// -----------------------------------------------------------------

			if (
				verified_target &&
				verified_target.identity_record ===
					created_identity_record
			) {
				console.log(
					"[JPR] SUCCESS: Identity Record linked:",
					created_identity_record
				);


				/*
				 * Only clear sessionStorage after
				 * the value has actually been verified.
				 */
				clear_identity_record_restore_storage();
			} else {
				console.error(
					"[JPR] FAILED: Identity Record is still not linked."
				);

				console.error(
					"[JPR] Final rows:",
					verified_rows
				);

				/*
				 * Do NOT clear sessionStorage.
				 *
				 * This preserves the context so the
				 * problem can be diagnosed/retried.
				 */
			}


			frm.__restoring_identity_record_context =
				false;

			frm.__identity_record_restore_running =
				false;


			console.log(
				"[JPR] Release restoration finished."
			);
		},
		500
	);
}


// -----------------------------------------------------------------------------
// CLEAR IDENTITY RECORD RESTORE STORAGE
// -----------------------------------------------------------------------------

function clear_identity_record_restore_storage() {
	console.log(
		"[JPR] Clearing Identity Record restore storage."
	);

	sessionStorage.removeItem(
		IDENTITY_RECORD_CONTEXT_KEY
	);

	sessionStorage.removeItem(
		IDENTITY_RECORD_CREATED_KEY
	);
}


// -----------------------------------------------------------------------------
// RESTORE CHILD TABLE
// -----------------------------------------------------------------------------

function restore_child_table(
	frm,
	fieldname,
	rows
) {
	if (
		!Array.isArray(rows)
	) {
		console.log(
			"[JPR] No rows to restore for:",
			fieldname
		);

		return;
	}


	/*
	 * Remove the current generated rows.
	 */
	frm.doc[fieldname] =
		[];


	rows.forEach(
		(row) => {
			const restored_row =
				frappe.model.add_child(
					frm.doc,
					row.doctype,
					fieldname
				);


			Object.keys(
				row
			).forEach(
				(row_fieldname) => {
					if (
						[
							"name",
							"parent",
							"parentfield",
							"parenttype",
							"idx",
							"__islocal",
							"__unsaved",
						].includes(
							row_fieldname
						)
					) {
						return;
					}


					restored_row[
						row_fieldname
					] =
						row[
							row_fieldname
						];
				}
			);
		}
	);
}


// -----------------------------------------------------------------------------
// CLEAR RELEASE FACT TABLES
// -----------------------------------------------------------------------------

function clear_release_fact_tables(
	frm
) {
	if (
		frm.__restoring_identity_record_context
	) {
		console.log(
			"[JPR] Clearing fact tables skipped during restore."
		);

		return;
	}


	console.log(
		"[JPR] Clearing release fact tables."
	);


	frm.clear_table(
		"identifier_facts"
	);

	frm.clear_table(
		"statutory_registration_facts"
	);

	frm.clear_table(
		"tax_obligation_facts"
	);

	frm.clear_table(
		"compliance_entitlement_facts"
	);


	frm.refresh_field(
		"identifier_facts"
	);

	frm.refresh_field(
		"statutory_registration_facts"
	);

	frm.refresh_field(
		"tax_obligation_facts"
	);

	frm.refresh_field(
		"compliance_entitlement_facts"
	);
}


// -----------------------------------------------------------------------------
// LOAD TEMPLATE REQUIREMENTS
// -----------------------------------------------------------------------------

function load_template_requirements(
	frm
) {
	if (
		frm.__restoring_identity_record_context
	) {
		console.log(
			"[JPR] Template load skipped during restore."
		);

		return;
	}


	frappe.call({
		method:
			"frappe.client.get",

		args: {
			doctype:
				"Jurisdiction Compliance Template",

			name:
				frm.doc
					.jurisdiction_compliance_template,
		},

		callback(r) {
			/*
			 * The user may have returned from Identity
			 * Record while this asynchronous request
			 * was still running.
			 *
			 * Never let that response destroy the
			 * restored Release.
			 */
			if (
				frm.__restoring_identity_record_context
			) {
				console.log(
					"[JPR] Template response ignored during restore."
				);

				return;
			}


			console.log(
				"[JPR] template response:",
				r.message
			);


			if (
				!r.message
			) {
				return;
			}


			const template =
				r.message;


			// -----------------------------------------------------------------
			// CLEAR EXISTING GENERATED ROWS
			// -----------------------------------------------------------------

			clear_release_fact_tables(
				frm
			);


			// -----------------------------------------------------------------
			// IDENTIFIER FACTS
			// -----------------------------------------------------------------

			if (
				Array.isArray(
					template.identifier_record
				)
			) {
				template
					.identifier_record
					.forEach(
						(requirement) => {
							const row =
								frm.add_child(
									"identifier_facts"
								);


							row.requirement_type =
								requirement
									.requirement_type ||
								"";


							row.is_mandatory =
								requirement
									.is_mandatory ||
								"No";
						}
					);
			}


			// -----------------------------------------------------------------
			// STATUTORY REGISTRATION FACTS
			// -----------------------------------------------------------------

			if (
				Array.isArray(
					template
						.statutory_registration_requirement
				)
			) {
				template
					.statutory_registration_requirement
					.forEach(
						(requirement) => {
							const row =
								frm.add_child(
									"statutory_registration_facts"
								);


							row.requirement_type =
								requirement
									.requirement_type ||
								"";


							row.is_mandatory =
								requirement
									.is_mandatory ||
								"No";
						}
					);
			}


			// -----------------------------------------------------------------
			// TAX OBLIGATION FACTS
			// -----------------------------------------------------------------

			if (
				Array.isArray(
					template.tax_details
				)
			) {
				template
					.tax_details
					.forEach(
						(requirement) => {
							const row =
								frm.add_child(
									"tax_obligation_facts"
								);


							row.requirement_type =
								requirement
									.requirement_type ||
								"";


							row.is_mandatory =
								requirement
									.is_mandatory ||
								"No";
						}
					);
			}


			// -----------------------------------------------------------------
			// REFRESH TABLES
			// -----------------------------------------------------------------

			frm.refresh_field(
				"identifier_facts"
			);

			frm.refresh_field(
				"statutory_registration_facts"
			);

			frm.refresh_field(
				"tax_obligation_facts"
			);


			console.log(
				"[JPR] identifier facts after template load:",
				frm.doc.identifier_facts
			);

			console.log(
				"[JPR] statutory facts after template load:",
				frm.doc.statutory_registration_facts
			);

			console.log(
				"[JPR] tax facts after template load:",
				frm.doc.tax_obligation_facts
			);
		},
	});
}


// -----------------------------------------------------------------------------
// IDENTITY RECORD LINK QUERIES
// -----------------------------------------------------------------------------

function configure_identity_record_queries(
	frm
) {
	[
		"identifier_facts",
		"statutory_registration_facts",
		"tax_obligation_facts",
	].forEach(
		(table_fieldname) => {
			const grid =
				frm.fields_dict[
					table_fieldname
				]?.grid;


			if (
				!grid
			) {
				return;
			}


			const identity_record_field =
				grid.get_field(
					IDENTITY_RECORD_LINK_FIELD
				);


			if (
				!identity_record_field
			) {
				return;
			}


			identity_record_field.get_query =
				function () {
					return {
						filters: {
							profile:
								frm.doc
									.profile ||
								"",

							evidence_type:
								get_identity_record_evidence_type(
									table_fieldname
								),
						},
					};
				};
		}
	);
}


// -----------------------------------------------------------------------------
// TEMPLATE QUERY
// -----------------------------------------------------------------------------

function configure_template_query(
	frm
) {
	const field =
		frm.fields_dict
			.jurisdiction_compliance_template;


	if (
		!field
	) {
		return;
	}


	field.get_query =
		function () {
			const filters =
				{};


			if (
				frm.doc.profile
			) {
				filters.country =
					frm.doc.country;

				filters.party_kind =
					frm.doc.party_kind;
			}


			return {
				filters,
			};
		};
}
