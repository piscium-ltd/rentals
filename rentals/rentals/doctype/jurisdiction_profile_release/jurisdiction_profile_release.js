
/*
 * Jurisdiction Profile Release
 * Copyright (c) 2026, Piscium Solutions LTD
 *
 * Profile ownership: PLCI.portal_user
 * Compatible with the existing Identity Record return flow.
 */

const IDENTITY_RECORD_CONTEXT_KEY =
    "jurisdiction_profile_release_identity_record_context";

const IDENTITY_RECORD_CREATED_KEY =
    "jurisdiction_profile_release_identity_record_created";

const IDENTITY_RECORD_LINK_FIELD = "identity_record";
const IDENTITY_RECORD_DOCTYPE = "Identity Record";
const JURISDICTION_PROFILE_RELEASE_DOCTYPE =
    "Jurisdiction Profile Release";
const PROFILE_DOCTYPE =
    "Party Legal and Compliance Identity";

const RELEASE_FACT_TABLES = [
    "identifier_facts",
    "statutory_registration_facts",
    "tax_obligation_facts",
    "compliance_entitlement_facts"
];


// ============================================================
// FORM EVENTS
// ============================================================

frappe.ui.form.on(
    "Jurisdiction Profile Release",
    {
        setup(frm) {
            setup_identity_record_create_handler();
            configure_profile_query(frm);
            configure_identity_record_queries(frm);
            configure_template_query(frm);
        },

        onload(frm) {
            restore_release_after_identity_record(frm);
            autofill_logged_in_profile(frm);
        },

        refresh(frm) {
            setup_identity_record_create_handler();
            configure_profile_query(frm);
            configure_identity_record_queries(frm);
            configure_template_query(frm);

            restore_release_after_identity_record(frm);
            autofill_logged_in_profile(frm);
        },

        profile(frm) {
            if (
                frm.__restoring_identity_record_context
            ) {
                return;
            }

            clear_release_fact_tables(frm);
        },

        jurisdiction_compliance_template(frm) {
            if (
                frm.__restoring_identity_record_context
            ) {
                return;
            }

            if (!frm.doc.jurisdiction_compliance_template) {
                clear_release_fact_tables(frm);
                return;
            }

            load_template_requirements(frm);
        }
    }
);


// ============================================================
// USER PROFILE ACCESS
// ============================================================

function user_has_profile_admin_access() {
    return (
        frappe.session.user === "Administrator" ||
        frappe.user.has_role("System Manager")
    );
}


// ============================================================
// FILTER PROFILE LINK TO LOGGED-IN USER
// ============================================================

function configure_profile_query(frm) {
    frm.set_query("profile", function () {
        if (user_has_profile_admin_access()) {
            return {};
        }

        return {
            filters: {
                portal_user: frappe.session.user
            }
        };
    });
}


// ============================================================
// AUTOMATICALLY SELECT LOGGED-IN USER PROFILE
// ============================================================

async function autofill_logged_in_profile(frm) {
    const user = frappe.session.user;

    if (
        !frm.is_new() ||
        !user ||
        user === "Guest" ||
        user_has_profile_admin_access() ||
        frm.doc.profile ||
        frm.__profile_lookup_running ||
        frm.__restoring_identity_record_context ||
        frm.__identity_record_restore_running ||
        sessionStorage.getItem(
            IDENTITY_RECORD_CONTEXT_KEY
        )
    ) {
        return;
    }

    frm.__profile_lookup_running = true;

    const original_form_name = frm.doc.name;

    try {
        const profiles = await frappe.db.get_list(
            PROFILE_DOCTYPE,
            {
                filters: {
                    portal_user: user
                },
                fields: ["name"],
                limit: 2
            }
        );

        // Protect against navigation or restoration while
        // the asynchronous lookup was running.
        if (
            !frm.is_new() ||
            frm.doc.name !== original_form_name ||
            frm.doc.profile ||
            frm.__restoring_identity_record_context ||
            frm.__identity_record_restore_running ||
            sessionStorage.getItem(
                IDENTITY_RECORD_CONTEXT_KEY
            )
        ) {
            return;
        }

        if (profiles.length === 1) {
            await frm.set_value(
                "profile",
                profiles[0].name
            );

            frm.refresh_field("profile");

            console.log(
                "[JPR] Profile automatically selected:",
                profiles[0].name
            );

            return;
        }

        if (profiles.length > 1) {
            frappe.msgprint(
                __(
                    "Multiple legal and compliance profiles are linked to your account. Contact an administrator."
                )
            );

            return;
        }

        frappe.show_alert({
            message: __(
                "No accessible legal and compliance profile is linked to your account."
            ),
            indicator: "orange"
        });

    } catch (error) {
        console.error(
            "[JPR] Profile lookup failed:",
            error
        );

        frappe.show_alert({
            message: __(
                "Unable to retrieve your legal and compliance profile. Check profile read access."
            ),
            indicator: "red"
        });

    } finally {
        frm.__profile_lookup_running = false;
    }
}


// ============================================================
// IDENTITY RECORD EVIDENCE TYPE
// ============================================================

function get_identity_record_evidence_type(
    child_table_fieldname
) {
    switch (child_table_fieldname) {
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


// ============================================================
// IDENTITY RECORD REQUIREMENT FIELD
// ============================================================

function get_identity_record_requirement_field(
    child_table_fieldname
) {
    switch (child_table_fieldname) {
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


// ============================================================
// INTERCEPT CREATE NEW IDENTITY RECORD
// ============================================================

function setup_identity_record_create_handler() {
    const ControlLink =
        frappe.ui.form.ControlLink;

    if (
        ControlLink.prototype
            .__jpr_identity_record_new_doc_patched
    ) {
        return;
    }

    const original_new_doc =
        ControlLink.prototype.new_doc;

    ControlLink.prototype.new_doc = function () {
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

        if (!is_identity_record_link) {
            return original_new_doc.apply(
                this,
                arguments
            );
        }

        const frm = field.frm;
        const row = field.doc;

        if (!row || !row.parentfield) {
            console.error(
                "[JPR] Identity Record child row unavailable."
            );

            return original_new_doc.apply(
                this,
                arguments
            );
        }

        const child_table_fieldname =
            row.parentfield;

        const evidence_type =
            get_identity_record_evidence_type(
                child_table_fieldname
            );

        const requirement_field =
            get_identity_record_requirement_field(
                child_table_fieldname
            );

        open_identity_record_from_release(
            frm,
            row,
            evidence_type,
            requirement_field,
            child_table_fieldname
        );

        return false;
    };

    ControlLink.prototype
        .__jpr_identity_record_new_doc_patched = true;
}


// ============================================================
// OPEN PREFILLED IDENTITY RECORD
// ============================================================

function open_identity_record_from_release(
    frm,
    row,
    evidence_type,
    requirement_field,
    child_table_fieldname
) {
    // Save the complete unsaved release context.
    const context = {
        release_name: frm.doc.name,

        child_table_fieldname:
            child_table_fieldname,

        child_doctype: row.doctype,
        child_row_name: row.name,
        child_row_idx: row.idx,

        evidence_type: evidence_type,
        requirement_field: requirement_field,

        requirement_type:
            row.requirement_type || "",

        profile: frm.doc.profile || "",
        party_kind: frm.doc.party_kind || "",
        country: frm.doc.country || "",

        jurisdiction_compliance_template:
            frm.doc.jurisdiction_compliance_template || "",

        is_mandatory:
            row.is_mandatory || "",

        identifier_facts:
            frm.doc.identifier_facts || [],

        statutory_registration_facts:
            frm.doc.statutory_registration_facts || [],

        tax_obligation_facts:
            frm.doc.tax_obligation_facts || [],

        compliance_entitlement_facts:
            frm.doc.compliance_entitlement_facts || []
    };

    sessionStorage.setItem(
        IDENTITY_RECORD_CONTEXT_KEY,
        JSON.stringify(context)
    );

    sessionStorage.removeItem(
        IDENTITY_RECORD_CREATED_KEY
    );

    const values = {
        profile: frm.doc.profile || "",
        party_kind: frm.doc.party_kind || "",
        country: frm.doc.country || "",
        evidence_type: evidence_type || "",

        source_class:
            row.source_class || "Certified Copy",

        document_type: "",
        doc_type: "",
        tax_details: ""
    };

    if (
        row.requirement_type &&
        requirement_field
    ) {
        values[requirement_field] =
            row.requirement_type;
    }

    frappe.model.with_doctype(
        IDENTITY_RECORD_DOCTYPE,
        function () {
            const identity_record =
                frappe.model.get_new_doc(
                    IDENTITY_RECORD_DOCTYPE
                );

            Object.keys(values).forEach(
                function (fieldname) {
                    identity_record[fieldname] =
                        values[fieldname];
                }
            );

            frappe.set_route(
                "Form",
                IDENTITY_RECORD_DOCTYPE,
                identity_record.name
            );
        }
    );
}


// ============================================================
// RESTORE RELEASE AFTER IDENTITY RECORD CREATION
// ============================================================

function restore_release_after_identity_record(frm) {
    if (
        frm.__identity_record_restore_running
    ) {
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

    if (
        !stored_context ||
        !created_identity_record ||
        !frm.is_new()
    ) {
        return;
    }

    let context;

    try {
        context = JSON.parse(stored_context);
    } catch (error) {
        console.error(
            "[JPR] Invalid restoration context:",
            error
        );

        clear_identity_record_restore_storage();
        return;
    }

    // Do not restore onto a different new release.
    if (
        context.release_name &&
        context.release_name !== frm.doc.name
    ) {
        console.warn(
            "[JPR] Release name differs during restore.",
            context.release_name,
            frm.doc.name
        );

        // Frappe can generate another local name when
        // returning to an unsaved document.
        // Continue only when the form is still new.
    }

    frm.__identity_record_restore_running = true;
    frm.__restoring_identity_record_context = true;

    try {
        // Restore parent fields.
        frm.doc.profile = context.profile || "";
        frm.doc.party_kind = context.party_kind || "";
        frm.doc.country = context.country || "";

        frm.doc.jurisdiction_compliance_template =
            context.jurisdiction_compliance_template || "";

        // Restore all child tables.
        RELEASE_FACT_TABLES.forEach(
            function (fieldname) {
                restore_child_table(
                    frm,
                    fieldname,
                    context[fieldname]
                );
            }
        );

        const rows =
            frm.doc[
                context.child_table_fieldname
            ] || [];

        let target_row = null;

        // First locate by original row index.
        if (context.child_row_idx) {
            target_row = rows.find(
                function (row) {
                    return (
                        Number(row.idx) ===
                        Number(context.child_row_idx)
                    );
                }
            );
        }

        // Fallback to requirement type.
        if (
            !target_row &&
            context.requirement_type
        ) {
            target_row = rows.find(
                function (row) {
                    return (
                        row.requirement_type ===
                        context.requirement_type
                    );
                }
            );
        }

        if (!target_row) {
            console.error(
                "[JPR] Could not locate restored child row.",
                context
            );

            return;
        }

        // Link the saved Identity Record.
        target_row.identity_record =
            created_identity_record;

        target_row.__unsaved = 1;

        frappe.model.set_value(
            target_row.doctype,
            target_row.name,
            IDENTITY_RECORD_LINK_FIELD,
            created_identity_record
        );

        frm.dirty();

        frm.refresh_field("profile");
        frm.refresh_field("party_kind");
        frm.refresh_field("country");

        frm.refresh_field(
            "jurisdiction_compliance_template"
        );

        RELEASE_FACT_TABLES.forEach(
            function (fieldname) {
                frm.refresh_field(fieldname);
            }
        );

        const target_row_name = target_row.name;

        // Verify the restored relationship after
        // Frappe has refreshed the child grid.
        setTimeout(function () {
            try {
                const latest_rows =
                    frm.doc[
                        context.child_table_fieldname
                    ] || [];

                let latest_target =
                    latest_rows.find(
                        function (row) {
                            return (
                                row.name ===
                                target_row_name
                            );
                        }
                    );

                if (
                    !latest_target &&
                    context.child_row_idx
                ) {
                    latest_target = latest_rows.find(
                        function (row) {
                            return (
                                Number(row.idx) ===
                                Number(
                                    context.child_row_idx
                                )
                            );
                        }
                    );
                }

                if (
                    !latest_target &&
                    context.requirement_type
                ) {
                    latest_target = latest_rows.find(
                        function (row) {
                            return (
                                row.requirement_type ===
                                context.requirement_type
                            );
                        }
                    );
                }

                if (!latest_target) {
                    console.error(
                        "[JPR] Restored child row disappeared."
                    );

                    return;
                }

                latest_target.identity_record =
                    created_identity_record;

                latest_target.__unsaved = 1;

                frm.dirty();

                frm.refresh_field(
                    context.child_table_fieldname
                );

                const verified_rows =
                    frm.doc[
                        context.child_table_fieldname
                    ] || [];

                const verified_target =
                    verified_rows.find(
                        function (row) {
                            return (
                                row.name ===
                                latest_target.name
                            );
                        }
                    );

                if (
                    verified_target &&
                    verified_target.identity_record ===
                        created_identity_record
                ) {
                    console.log(
                        "[JPR] Identity Record linked:",
                        created_identity_record
                    );

                    clear_identity_record_restore_storage();
                } else {
                    console.error(
                        "[JPR] Identity Record link verification failed."
                    );
                }
            } finally {
                frm.__restoring_identity_record_context =
                    false;

                frm.__identity_record_restore_running =
                    false;
            }
        }, 500);

    } catch (error) {
        console.error(
            "[JPR] Release restoration failed:",
            error
        );

        frm.__restoring_identity_record_context = false;
        frm.__identity_record_restore_running = false;
    }
}


// ============================================================
// CLEAR RESTORATION STORAGE
// ============================================================

function clear_identity_record_restore_storage() {
    sessionStorage.removeItem(
        IDENTITY_RECORD_CONTEXT_KEY
    );

    sessionStorage.removeItem(
        IDENTITY_RECORD_CREATED_KEY
    );
}


// ============================================================
// RESTORE CHILD TABLE
// ============================================================

function restore_child_table(frm, fieldname, rows) {
    if (!Array.isArray(rows)) {
        return;
    }

    frm.doc[fieldname] = [];

    rows.forEach(function (row) {
        const restored_row =
            frappe.model.add_child(
                frm.doc,
                row.doctype,
                fieldname
            );

        Object.keys(row).forEach(
            function (fieldname_to_copy) {
                if (
                    [
                        "name",
                        "parent",
                        "parentfield",
                        "parenttype",
                        "idx",
                        "__islocal",
                        "__unsaved"
                    ].includes(fieldname_to_copy)
                ) {
                    return;
                }

                restored_row[fieldname_to_copy] =
                    row[fieldname_to_copy];
            }
        );
    });
}


// ============================================================
// CLEAR RELEASE FACT TABLES
// ============================================================

function clear_release_fact_tables(frm) {
    if (
        frm.__restoring_identity_record_context
    ) {
        return;
    }

    RELEASE_FACT_TABLES.forEach(
        function (fieldname) {
            frm.clear_table(fieldname);
            frm.refresh_field(fieldname);
        }
    );
}


// ============================================================
// LOAD JURISDICTION COMPLIANCE TEMPLATE
// ============================================================

function load_template_requirements(frm) {
    if (
        frm.__restoring_identity_record_context
    ) {
        return;
    }

    const selected_template =
        frm.doc.jurisdiction_compliance_template;

    if (!selected_template) {
        return;
    }

    frappe.call({
        method: "frappe.client.get",

        args: {
            doctype: "Jurisdiction Compliance Template",
            name: selected_template
        },

        callback(r) {
            if (
                frm.__restoring_identity_record_context ||
                frm.__identity_record_restore_running ||
                sessionStorage.getItem(
                    IDENTITY_RECORD_CONTEXT_KEY
                ) ||
                frm.doc.jurisdiction_compliance_template !==
                    selected_template
            ) {
                return;
            }

            if (!r.message) {
                return;
            }

            const template = r.message;

            clear_release_fact_tables(frm);

            // Identifier Facts
            if (
                Array.isArray(
                    template.identifier_record
                )
            ) {
                template.identifier_record.forEach(
                    function (requirement) {
                        const row = frm.add_child(
                            "identifier_facts"
                        );

                        row.requirement_type =
                            requirement.requirement_type ||
                            "";

                        row.is_mandatory =
                            requirement.is_mandatory ||
                            "No";
                    }
                );
            }

            // Statutory Registration Facts
            if (
                Array.isArray(
                    template.statutory_registration_requirement
                )
            ) {
                template
                    .statutory_registration_requirement
                    .forEach(function (requirement) {
                        const row = frm.add_child(
                            "statutory_registration_facts"
                        );

                        row.requirement_type =
                            requirement.requirement_type ||
                            "";

                        row.is_mandatory =
                            requirement.is_mandatory ||
                            "No";
                    });
            }

            // Tax Obligation Facts
            if (
                Array.isArray(
                    template.tax_details
                )
            ) {
                template.tax_details.forEach(
                    function (requirement) {
                        const row = frm.add_child(
                            "tax_obligation_facts"
                        );

                        row.requirement_type =
                            requirement.requirement_type ||
                            "";

                        row.is_mandatory =
                            requirement.is_mandatory ||
                            "No";
                    }
                );
            }

            frm.refresh_field("identifier_facts");
            frm.refresh_field(
                "statutory_registration_facts"
            );
            frm.refresh_field(
                "tax_obligation_facts"
            );

            frm.dirty();
        }
    });
}


// ============================================================
// IDENTITY RECORD LINK QUERIES
// ============================================================

function configure_identity_record_queries(frm) {
    [
        "identifier_facts",
        "statutory_registration_facts",
        "tax_obligation_facts"
    ].forEach(function (table_fieldname) {
        const grid =
            frm.fields_dict[
                table_fieldname
            ]?.grid;

        if (!grid) {
            return;
        }

        const identity_record_field =
            grid.get_field(
                IDENTITY_RECORD_LINK_FIELD
            );

        if (!identity_record_field) {
            return;
        }

        identity_record_field.get_query =
            function () {
                return {
                    filters: {
                        profile: frm.doc.profile || "",

                        evidence_type:
                            get_identity_record_evidence_type(
                                table_fieldname
                            )
                    }
                };
            };
    });
}


// ============================================================
// JURISDICTION COMPLIANCE TEMPLATE QUERY
// ============================================================

function configure_template_query(frm) {
    const field =
        frm.fields_dict
            .jurisdiction_compliance_template;

    if (!field) {
        return;
    }

    field.get_query = function () {
        const filters = {};

        if (frm.doc.profile) {
            filters.country = frm.doc.country;
            filters.party_kind = frm.doc.party_kind;
        }

        return {
            filters: filters
        };
    };
}


const JPR_AUTO_JCT_DOCTYPE =
    "Jurisdiction Compliance Template";

const JPR_AUTO_PLCI_DOCTYPE =
    "Party Legal and Compliance Identity";


frappe.ui.form.on("Jurisdiction Profile Release", {
    refresh(frm) {
        jpr_configure_active_template_query(frm);
        jpr_auto_select_active_template(frm);
    },

    profile(frm) {
        if (
            frm.__restoring_identity_record_context ||
            frm.__identity_record_restore_running
        ) {
            return;
        }

        // Invalidate requests started for the previous profile.
        frm.__auto_jct_sequence =
            (frm.__auto_jct_sequence || 0) + 1;

        frm.__auto_jct_profile_details = null;

        // A different profile requires a different template.
        if (frm.doc.jurisdiction_compliance_template) {
            frm.set_value(
                "jurisdiction_compliance_template",
                ""
            );
        }

        jpr_auto_select_active_template(frm);
    }
});


function jpr_configure_active_template_query(frm) {
    frm.set_query(
        "jurisdiction_compliance_template",
        function () {
            const filters = {
                docstatus: 1,
                template_status: "Active"
            };

            const profile =
                frm.__auto_jct_profile_details;

            if (profile) {
                filters.country = profile.country;
                filters.party_kind = profile.party_kind;

                if (profile.party_kind === "Individual") {
                    filters.has_business_name =
                        profile.has_business_name;

                    filters.organization_type =
                        ["is", "not set"];
                }

                if (profile.party_kind === "Organization") {
                    filters.organization_type =
                        profile.organization_type;

                    filters.has_business_name =
                        ["is", "not set"];
                }
            } else {
                if (frm.doc.country) {
                    filters.country = frm.doc.country;
                }

                if (frm.doc.party_kind) {
                    filters.party_kind = frm.doc.party_kind;
                }
            }

            return { filters };
        }
    );
}


async function jpr_auto_select_active_template(frm) {
    if (
        !frm.is_new() ||
        !frm.doc.profile ||
        frm.doc.jurisdiction_compliance_template ||
        frm.__restoring_identity_record_context ||
        frm.__identity_record_restore_running ||
        sessionStorage.getItem(
            "jurisdiction_profile_release_identity_record_context"
        )
    ) {
        return;
    }

    const profile_name = frm.doc.profile;
    const release_name = frm.doc.name;

    const sequence =
        (frm.__auto_jct_sequence || 0) + 1;

    frm.__auto_jct_sequence = sequence;

    function is_current_request() {
        return (
            frm.is_new() &&
            frm.doc.name === release_name &&
            frm.doc.profile === profile_name &&
            frm.__auto_jct_sequence === sequence &&
            !frm.doc.jurisdiction_compliance_template &&
            !frm.__restoring_identity_record_context &&
            !frm.__identity_record_restore_running &&
            !sessionStorage.getItem(
                "jurisdiction_profile_release_identity_record_context"
            )
        );
    }

    try {
        // Obtain authoritative classification from PLCI.
        const response = await frappe.db.get_value(
            JPR_AUTO_PLCI_DOCTYPE,
            profile_name,
            [
                "country",
                "party_kind",
                "has_business_name",
                "organization_type"
            ]
        );

        if (!is_current_request()) {
            return;
        }

        const profile = response.message || {};

        if (!profile.country || !profile.party_kind) {
            frappe.show_alert({
                message: __(
                    "Profile country or party kind is missing."
                ),
                indicator: "orange"
            });
            return;
        }

        const filters = {
            country: profile.country,
            party_kind: profile.party_kind,
            docstatus: 1,
            template_status: "Active"
        };

        if (profile.party_kind === "Individual") {
            if (
                !["Yes", "No"].includes(
                    profile.has_business_name
                )
            ) {
                frappe.show_alert({
                    message: __(
                        "Has Business Name must be Yes or No."
                    ),
                    indicator: "orange"
                });
                return;
            }

            filters.has_business_name =
                profile.has_business_name;

            filters.organization_type =
                ["is", "not set"];

        } else if (
            profile.party_kind === "Organization"
        ) {
            if (!profile.organization_type) {
                frappe.show_alert({
                    message: __(
                        "Organization Type is missing from the profile."
                    ),
                    indicator: "orange"
                });
                return;
            }

            filters.organization_type =
                profile.organization_type;

            filters.has_business_name =
                ["is", "not set"];

        } else {
            return;
        }

        frm.__auto_jct_profile_details = profile;

        // The template lifecycle is managed by the
        // Jurisdiction Compliance Template controller.
        const templates = await frappe.db.get_list(
            JPR_AUTO_JCT_DOCTYPE,
            {
                filters: filters,
                fields: [
                    "name",
                    "legal_effective_from",
                    "legal_effective_to"
                ],
                limit: 20
            }
        );

        if (!is_current_request()) {
            return;
        }

        const today = frappe.datetime.get_today();

        const matching_templates =
            templates.filter(function (template) {
                return (
                    template.legal_effective_from &&
                    template.legal_effective_from <= today &&
                    (
                        !template.legal_effective_to ||
                        template.legal_effective_to >= today
                    )
                );
            });

        if (matching_templates.length === 1) {
            const selected =
                matching_templates[0].name;

            await frm.set_value(
                "jurisdiction_compliance_template",
                selected
            );

            console.log(
                "[JPR] Active Compliance Template selected:",
                selected
            );

            frappe.show_alert({
                message: __(
                    "Active compliance template selected automatically."
                ),
                indicator: "green"
            });

            return;
        }

        if (matching_templates.length === 0) {
            frappe.show_alert({
                message: __(
                    "No applicable Active compliance template was found."
                ),
                indicator: "orange"
            });
        } else {
            frappe.msgprint(
                __(
                    "Multiple Active compliance templates match this profile. Contact an administrator."
                )
            );
        }

    } catch (error) {
        if (is_current_request()) {
            console.error(
                "[JPR] Automatic template selection failed:",
                error
            );

            frappe.show_alert({
                message: __(
                    "Unable to retrieve the Active compliance template."
                ),
                indicator: "red"
            });
        }
    }
}
