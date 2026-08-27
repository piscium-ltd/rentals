// Copyright (c) 2025, Piscium Solutions LTD and contributors
// For license information, please see license.txt

const PROPERTY_SETUP_POLL_MS = 2000;
const PROPERTY_SETUP_MAX_POLLS = 30;

frappe.ui.form.on("Property", {
	setup(frm) {
		frm.set_query("landlord", () => ({
			filters: {
				status: "Active",
				company: ["is", "set"],
			},
		}));
	},

	refresh(frm) {
		// Refresh must be read-only. Server-derived valuation fields are already canonical
		// after save; mutating form setters here can mark a saved document dirty.
		update_accounting_model_ui(frm);
		update_setup_indicator(frm);
		configure_asset_actions(frm);

		if (!frm.is_new() && ["Pending", "In Progress"].includes(frm.doc.setup_status)) {
			poll_setup_status(frm);
		}
	},

	after_save(frm) {
		if (["Pending", "In Progress"].includes(frm.doc.setup_status)) {
			frappe.show_alert({
				message: __("Property saved. ERPNext Asset setup is continuing in the background."),
				indicator: "blue",
			}, 7);
			poll_setup_status(frm, true);
		}
	},

	accounting_model(frm) {
		if (frm.doc.accounting_model === "Fair Value Model") {
			frm.set_value("calculate_depreciation", 0);
		} else if (frm.is_new() && frm.doc.calculate_depreciation === 0) {
			frm.set_value("calculate_depreciation", 1);
		}

		update_current_values(frm);
		update_accounting_model_ui(frm);
	},

	calculate_depreciation(frm) {
		update_accounting_model_ui(frm);
	},

	acquisition_cost(frm) {
		update_accounting_model_ui(frm);
	},
});

frappe.ui.form.on("Valuation History", {
	valuation_date(frm) {
		update_current_values(frm);
	},
	valued_amount(frm) {
		update_current_values(frm);
	},
	valuation_history_add(frm) {
		update_current_values(frm);
	},
	valuation_history_remove(frm) {
		update_current_values(frm);
	},
});

function update_current_values(frm) {
	if (frm.doc.accounting_model !== "Fair Value Model") {
		set_if_changed(frm, "current_fair_value", null);
		set_if_changed(frm, "last_valuation_date", null);
		return;
	}

	const rows = (frm.doc.valuation_history || []).filter(
		(row) => row.valuation_date && row.valued_amount
	);

	if (!rows.length) {
		set_if_changed(frm, "current_fair_value", null);
		set_if_changed(frm, "last_valuation_date", null);
		return;
	}

	const latest = rows.reduce((current, row) => {
		if (!current) return row;
		return row.valuation_date > current.valuation_date ? row : current;
	}, null);

	set_if_changed(frm, "current_fair_value", latest.valued_amount);
	set_if_changed(frm, "last_valuation_date", latest.valuation_date);
}

function set_if_changed(frm, fieldname, value) {
	const current = frm.doc[fieldname] ?? null;
	const next = value ?? null;
	if (current !== next) {
		frm.set_value(fieldname, value);
	}
}

function update_accounting_model_ui(frm) {
	const isFairValue = frm.doc.accounting_model === "Fair Value Model";
	const acquisitionCost = Number(frm.doc.acquisition_cost || 0);

	frm.set_df_property(
		"accounting_model",
		"description",
		isFairValue
			? __("Fair Value Model: no depreciation is created. Dated valuation changes are posted through ERPNext Asset Value Adjustment.")
			: __("Cost Model: acquisition cost is capitalized and depreciation can be scheduled automatically.")
	);

	frm.set_df_property(
		"acquisition_cost",
		"description",
		acquisitionCost > 0
			? __("This amount will become the linked ERPNext Asset Net Purchase Amount.")
			: __("Required for both models. Enter the property's initial capitalized acquisition cost.")
	);

	if (isFairValue) {
		frm.set_df_property(
			"valuation_history",
			"description",
			__("At least one valuation is required. The row with the latest date becomes Current Fair Value.")
		);
	}
}

function update_setup_indicator(frm) {
	if (frm.is_new() || !frm.doc.setup_status) {
		frm.set_intro("");
		return;
	}

	const indicators = {
		Pending: "orange",
		"In Progress": "blue",
		Completed: "green",
		Failed: "red",
	};

	const messages = {
		Pending: __("Property saved. ERPNext Asset setup is queued in the background."),
		"In Progress": __("Property saved. ERPNext Asset and accounting setup is running in the background; you can continue working."),
		Completed: __("Property setup completed successfully and the ERPNext Asset is linked."),
		Failed: __("Property Asset setup needs attention. Review the error below and use Actions → Retry Asset Setup."),
	};

	frm.set_intro(
		messages[frm.doc.setup_status] || __("Property Asset setup: {0}", [frm.doc.setup_status]),
		indicators[frm.doc.setup_status] || "blue"
	);
}

function configure_asset_actions(frm) {
	if (frm.is_new()) return;

	if (frm.doc.asset) {
		frm.add_custom_button(__("Open Asset"), () => {
			frappe.set_route("Form", "Asset", frm.doc.asset);
		}, __("Actions"));
	}

	if (frm.doc.setup_status !== "Failed") return;

	frm.add_custom_button(__("Retry Asset Setup"), () => {
		frappe.call({
			method: "rentals.rentals.doctype.property.property.retry_property_asset_setup",
			args: { property_name: frm.doc.name },
			freeze: false,
			callback() {
				frappe.show_alert({
					message: __("Property Asset setup queued. You can continue working."),
					indicator: "blue",
				}, 5);
				frm.doc.setup_status = "Pending";
				frm.doc.setup_error = "";
				frm.refresh_fields(["setup_status", "setup_error"]);
				update_setup_indicator(frm);
				poll_setup_status(frm, true);
			},
		});
	}, __("Actions"));
}

function sync_after_setup_poll(frm) {
	// A clean form can be safely reloaded so Frappe receives the canonical server
	// document and stays in the Saved state. If the user has started editing again,
	// do not reload and risk discarding those edits; refresh only the presentation.
	if (!frm.is_dirty()) {
		frm.reload_doc();
		return;
	}

	update_setup_indicator(frm);
	configure_asset_actions(frm);
}

function poll_setup_status(frm, reset = false) {
	if (frm.is_new() || frm.__property_setup_polling) return;
	if (reset) frm.__property_setup_poll_count = 0;

	frm.__property_setup_polling = true;
	frm.__property_setup_poll_count = frm.__property_setup_poll_count || 0;

	const poll = () => {
		if (
			frm.is_new()
			|| !frm.doc.name
			|| frm.__property_setup_poll_count >= PROPERTY_SETUP_MAX_POLLS
		) {
			frm.__property_setup_polling = false;
			return;
		}

		frm.__property_setup_poll_count += 1;
		frappe.db.get_value(
			"Property",
			frm.doc.name,
			["setup_status", "setup_error", "setup_completed_on", "asset"]
		).then((response) => {
			const values = response.message || {};
			const previous = frm.doc.setup_status;
			Object.assign(frm.doc, values);
			frm.refresh_fields(["setup_status", "setup_error", "setup_completed_on", "asset"]);
			update_setup_indicator(frm);

			if (values.setup_status === "Completed") {
				frm.__property_setup_polling = false;
				if (previous !== "Completed") {
					frappe.show_alert({
						message: __("Property setup completed and Asset {0} was linked.", [values.asset]),
						indicator: "green",
					}, 6);
				}
				sync_after_setup_poll(frm);
				return;
			}

			if (values.setup_status === "Failed") {
				frm.__property_setup_polling = false;
				sync_after_setup_poll(frm);
				frappe.show_alert({
					message: __("Property Asset setup needs attention. Use Actions → Retry Asset Setup."),
					indicator: "red",
				}, 7);
				return;
			}

			setTimeout(poll, PROPERTY_SETUP_POLL_MS);
		}).catch(() => {
			frm.__property_setup_polling = false;
		});
	};

	setTimeout(poll, PROPERTY_SETUP_POLL_MS);
}
