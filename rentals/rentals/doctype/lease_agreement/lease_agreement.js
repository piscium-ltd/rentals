// Copyright (c) 2025, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Lease Agreement", {
	refresh(frm) {
		// If rent_item is not already set, set it to 'Rent'
		if (!frm.doc.rent_item) {
			frm.set_value("rent_item", "Rent");
		}

		// Set dynamic filters
		frm.set_query("property", () => ({
			filters: { landlord: frm.doc.landlord },
		}));

		frm.set_query("unit", () => ({
			filters: {
				property: frm.doc.property,
				status: "Vacant",
			},
		}));

		// Filter chargeable services to avoid duplicates
		frm.fields_dict.chargeable_services.grid.get_field("service").get_query = function (
			doc,
			cdt,
			cdn
		) {
			const current_row = locals[cdt][cdn];
			const selected_services = (doc.chargeable_services || [])
				.filter((row) => row.name !== current_row.name && row.service)
				.map((row) => row.service);

			return {
				filters: {
					item_group: "Rental Chargeable Services",
					name: ["not in", selected_services],
				},
			};
		};

		// Filter security deposit types to avoid duplicates
		frm.fields_dict.security_deposits.grid.get_field("security_type").get_query = function (
			doc,
			cdt,
			cdn
		) {
			const current_row = locals[cdt][cdn];
			const selected_types = (doc.security_deposits || [])
				.filter((row) => row.name !== current_row.name && row.security_type)
				.map((row) => row.security_type);

			return {
				filters: {
					item_group: "Rental Security Deposits",
					name: ["not in", selected_types],
				},
			};
		};

		// Generate invoice button for submitted documents
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Generate Invoice"), function () {
				frappe.call({
					method: "rentals.tasks.daily.generate_sales_invoices",
					args: {
						lease_name: frm.doc.name,
						override_billing_date: true,
					},
					callback: function (r) {
						if (r.message?.invoices?.length > 0) {
							const links = r.message.invoices
								.map((inv) => {
									const url = `/app/sales-invoice/${inv}`;
									return `<a href="${url}" target="_blank">${inv}</a>`;
								})
								.join("<br>");

							frappe.msgprint({
								title: __(r.message.message),
								indicator: "green",
								message: __("<b>" + links + "<b>"),
							});

							frm.reload_doc();
						} else {
							frappe.msgprint(r.message.message || __("No invoices created."));
						}
					},
					error: () => {
						frappe.msgprint(__("Error generating sales invoice."));
					},
				});
			});
		}

		// Initial calculations
		calculate_chargeable_services_subtotal(frm);
		calculate_security_deposits_subtotal(frm);
		calculate_grand_total(frm);
	},

	tenant(frm) {
		if (frm.doc.tenant) {
			frappe.db.get_value("Tenant", frm.doc.tenant, "customer").then((r) => {
				if (r?.message?.customer) {
					frm.set_value("customer", r.message.customer);
				}
			});
		}
	},

	property(frm) {
		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Property Assignment",
				filters: { property: frm.doc.property },
				fields: ["name"],
				limit_page_length: 1,
			},
			callback(r) {
				if (r.message?.length > 0) {
					frm.set_value("property_assignment", r.message[0].name);
				}
			},
		});
	},

	start_date: validate_dates,
	end_date: validate_dates,

	billing_cycle(frm) {
		const next_date = get_billing_date(frm.doc.billing_cycle);
		if (next_date) {
			frm.set_value("billing_date", next_date);
		}
	},

	base_rental_amount: calculate_grand_total,
	chargeable_services_subtotal: calculate_grand_total,
	security_deposits_subtotal: calculate_grand_total,
});

frappe.ui.form.on("Chargeable Services", {
	rate: handle_chargeable_services_change,
	chargeable_services_add: handle_chargeable_services_change,
	chargeable_services_remove: handle_chargeable_services_change,

	billing_cycle(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const next_date = get_billing_date(row.billing_cycle);
		if (next_date) {
			frappe.model.set_value(cdt, cdn, "billing_date", next_date);
		}
	},
});

frappe.ui.form.on("Security Deposit", {
	rate: handle_security_deposits_change,
	security_deposits_add: handle_security_deposits_change,
	security_deposits_remove: handle_security_deposits_change,
});

// ---------- Helper Functions ---------- //

function get_billing_date(cycle) {
	const today_date = frappe.datetime.get_today();

	switch (cycle) {
		case "Daily":
			return frappe.datetime.add_days(today_date, 1);
		case "Monthly":
			return frappe.datetime.add_months(today_date, 1);
		case "Quarterly":
			return frappe.datetime.add_months(today_date, 3);
		case "Annually":
			return frappe.datetime.add_months(today_date, 12);
		default:
			return null;
	}
}

function calculate_chargeable_services_subtotal(frm) {
	const total = (frm.doc.chargeable_services || []).reduce((sum, row) => sum + flt(row.rate), 0);
	frm.set_value("chargeable_services_subtotal", total);
}

function calculate_security_deposits_subtotal(frm) {
	const total = (frm.doc.security_deposits || []).reduce((sum, row) => sum + flt(row.rate), 0);
	frm.set_value("security_deposits_subtotal", total);
}

function calculate_grand_total(frm) {
	const total =
		flt(frm.doc.base_rental_amount) +
		flt(frm.doc.chargeable_services_subtotal) +
		flt(frm.doc.security_deposits_subtotal);

	frm.set_value("grand_total", total);
}

function validate_dates(frm) {
	const { start_date, end_date } = frm.doc;
	if (start_date && end_date && end_date <= start_date) {
		frappe.msgprint({
			title: "Date Validation",
			message: "❌ End Date must be after Start Date.",
			indicator: "red",
		});
	}
}

function handle_chargeable_services_change(frm) {
	calculate_chargeable_services_subtotal(frm);
	calculate_grand_total(frm);
}

function handle_security_deposits_change(frm) {
	calculate_security_deposits_subtotal(frm);
	calculate_grand_total(frm);
}
