// Copyright (c) 2025, Piscium Solutions LTD and contributors
// For license information, please see license.txt

const LANDLORD_SETUP_POLL_MS = 2000;
const LANDLORD_SETUP_MAX_POLLS = 30;

frappe.ui.form.on("Landlord", {
	refresh(frm) {
		update_setup_indicator(frm);
		configure_setup_retry(frm);

		if (!frm.is_new() && ["Pending", "In Progress"].includes(frm.doc.setup_status)) {
			poll_setup_status(frm);
		}
	},

	after_save(frm) {
		if (["Pending", "In Progress"].includes(frm.doc.setup_status)) {
			frappe.show_alert({
				message: __("Landlord saved. Company and account setup is continuing in the background."),
				indicator: "blue",
			}, 7);
			poll_setup_status(frm, true);
		}
	},

	kra_pin(frm) {
		// Normalize the value once editing is committed, while preserving validation.
		const rawPin = frm.doc.kra_pin || "";
		const pin = rawPin.trim().toUpperCase();

		if (pin !== rawPin) {
			frm.set_value("kra_pin", pin);
		}

		const regex = /^[AP]{1}\d{9}[A-Z]{1}$/;

		if (!pin || regex.test(pin)) {
			frm.set_df_property("kra_pin", "description", "");
		} else {
			frm.set_df_property("kra_pin", "description", "Invalid KRA PIN format");
			setTimeout(() => {
				frm.fields_dict.kra_pin.$wrapper
					.find(".help-box")
					.removeClass("text-extra-muted")
					.css("color", "red");
			}, 100);
		}
	},
});

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
		Pending: __("Landlord saved. Related account setup is queued in the background."),
		"In Progress": __("Landlord saved. Company and account setup is running in the background; you can continue working."),
		Completed: __("Landlord setup completed successfully."),
		Failed: __("Landlord setup needs attention. Review the error below and use Actions → Retry Setup."),
	};

	frm.set_intro(
		messages[frm.doc.setup_status] || __("Landlord setup: {0}", [frm.doc.setup_status]),
		indicators[frm.doc.setup_status] || "blue"
	);
}

function configure_setup_retry(frm) {
	if (frm.is_new() || frm.doc.setup_status !== "Failed") return;

	frm.add_custom_button(__("Retry Setup"), () => {
		frappe.call({
			method: "rentals.rentals.doctype.landlord.landlord.retry_landlord_setup",
			args: { landlord_name: frm.doc.name },
			freeze: false,
			callback() {
				frappe.show_alert({
					message: __("Landlord setup queued. You can continue working."),
					indicator: "blue",
				}, 5);
				frm.set_value("setup_status", "Pending");
				frm.set_value("setup_error", "");
				update_setup_indicator(frm);
				poll_setup_status(frm, true);
			},
		});
	}, __("Actions"));
}

function poll_setup_status(frm, reset = false) {
	if (frm.is_new() || frm.__landlord_setup_polling) return;
	if (reset) frm.__landlord_setup_poll_count = 0;

	frm.__landlord_setup_polling = true;
	frm.__landlord_setup_poll_count = frm.__landlord_setup_poll_count || 0;

	const poll = () => {
		if (frm.is_new() || !frm.doc.name || frm.__landlord_setup_poll_count >= LANDLORD_SETUP_MAX_POLLS) {
			frm.__landlord_setup_polling = false;
			return;
		}

		frm.__landlord_setup_poll_count += 1;
		frappe.db.get_value(
			"Landlord",
			frm.doc.name,
			["setup_status", "setup_error", "setup_completed_on", "company", "user", "customer", "supplier"]
		).then((response) => {
			const values = response.message || {};
			const previous = frm.doc.setup_status;
			Object.assign(frm.doc, values);
			frm.refresh_fields([
				"setup_status", "setup_error", "setup_completed_on", "company", "user", "customer", "supplier",
			]);
			update_setup_indicator(frm);

			if (values.setup_status === "Completed") {
				frm.__landlord_setup_polling = false;
				if (previous !== "Completed") {
					frappe.show_alert({ message: __("Landlord setup completed."), indicator: "green" }, 5);
				}
				return;
			}

			if (values.setup_status === "Failed") {
				frm.__landlord_setup_polling = false;
				frm.refresh();
				frappe.show_alert({ message: __("Landlord setup needs attention. Use Retry Setup."), indicator: "red" }, 7);
				return;
			}

			setTimeout(poll, LANDLORD_SETUP_POLL_MS);
		}).catch(() => {
			frm.__landlord_setup_polling = false;
		});
	};

	setTimeout(poll, LANDLORD_SETUP_POLL_MS);
}
