// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Jurisdiction Profile Release", {
	profile(frm) {
		// Clear the selected template when the profile changes
		frm.set_value("jurisdiction_compliance_template", "");

		// Clear all requirements loaded from the previous template
		clear_release_fact_tables(frm);
	},

	jurisdiction_compliance_template(frm) {
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
					return;
				}

				const template = r.message;

				clear_release_fact_tables(frm);

				// Identifier Requirements
				(template.identifier_record || []).forEach((requirement) => {
					const row = frm.add_child("identifier_facts");

					row.requirement_type = requirement.requirement_type;
					row.is_mandatory = requirement.is_mandatory;
				});

				// Statutory Registration Requirements
				(template.statutory_registration_requirement || []).forEach(
					(requirement) => {
						const row = frm.add_child(
							"statutory_registration_facts"
						);

						row.requirement_type = requirement.requirement_type;
						row.is_mandatory = requirement.is_mandatory;
					}
				);

				// Tax Requirements
				(template.tax_details || []).forEach((requirement) => {
					const row = frm.add_child("tax_obligation_facts");

					row.requirement_type = requirement.requirement_type;
					row.is_mandatory = requirement.is_mandatory;
				});

				frm.refresh_field("identifier_facts");
				frm.refresh_field("statutory_registration_facts");
				frm.refresh_field("tax_obligation_facts");
			},
		});
	},

	setup(frm) {
		frm.set_query(
			"identity_record",
			"identifier_facts",
			function () {
				return {
					filters: {
						evidence_type: "Identifier Facts",
						profile: frm.doc.profile,
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
						profile: frm.doc.profile,
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
						profile: frm.doc.profile,
					},
				};
			}
		);

		frm.set_query("jurisdiction_compliance_template", function () {
			return {
				filters: {
					party_kind: frm.doc.party_kind,
				},
			};
		});
	},

	validate(frm) {
		validate_mandatory_identity_records(frm);
	},

	before_submit(frm) {
		validate_mandatory_identity_records(frm);
	},
});

function clear_release_fact_tables(frm) {
	frm.clear_table("identifier_facts");
	frm.clear_table("statutory_registration_facts");
	frm.clear_table("tax_obligation_facts");

	frm.refresh_field("identifier_facts");
	frm.refresh_field("statutory_registration_facts");
	frm.refresh_field("tax_obligation_facts");
}

function validate_mandatory_identity_records(frm) {
	const missing_requirements = [];

	function check_rows(rows) {
		(rows || []).forEach((row) => {
			const mandatory = String(row.is_mandatory || "")
				.trim()
				.toLowerCase();

			const is_mandatory = mandatory === "yes";

			if (is_mandatory && !row.identity_record) {
				missing_requirements.push(
					row.requirement_type || "Unnamed requirement"
				);
			}
		});
	}

	check_rows(frm.doc.identifier_facts);
	check_rows(frm.doc.statutory_registration_facts);
	check_rows(frm.doc.tax_obligation_facts);

	if (missing_requirements.length) {
		frappe.validated = false;

		frappe.msgprint({
			title: __("Mandatory Identity Record Missing"),
			indicator: "red",
			message: `
				<p>
					The following mandatory requirements do not have
					an Identity Record:
				</p>

				<ul>
					${missing_requirements
						.map(
							(requirement) =>
								`<li>${frappe.utils.escape_html(requirement)}</li>`
						)
						.join("")}
				</ul>

				<p>
					Please provide an Identity Record before continuing.
				</p>
			`,
		});
	}
}