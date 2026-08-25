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

		// Period-aware invoice generation for submitted, active leases.
		if (frm.doc.docstatus === 1 && frm.doc.status === "Active") {
			frm.add_custom_button(__("Generate Invoices"), function () {
				open_invoice_generation_dialog(frm);
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


function open_invoice_generation_dialog(frm) {
	const today = frappe.datetime.get_today();
	const default_through = frm.doc.billing_date || today;
	const dialog = new frappe.ui.Dialog({
		title: __("Generate Lease Invoices"),
		fields: [
			{
				fieldname: "generate_through",
				fieldtype: "Date",
				label: __("Generate Through"),
				reqd: 1,
				default: default_through,
				description: __(
					"Generation starts from the next ungenerated billing occurrence. Future dates are allowed."
				),
				onchange: () => update_invoice_generation_preview(frm, dialog),
			},
			{
				fieldname: "send_notifications",
				fieldtype: "Check",
				label: __("Send Tenant Invoice Notifications"),
				default: 0,
				description: __("Leave disabled for demos or bulk future-period generation."),
			},
			{
				fieldname: "preview_html",
				fieldtype: "HTML",
			},
		],
		primary_action_label: __("Generate Invoices"),
		primary_action(values) {
			const generate = () => generate_invoices_through(frm, dialog, values);
			if (values.generate_through > today) {
				frappe.confirm(
					__(
						"You are generating future-dated submitted Sales Invoices. These are real accounting documents. Continue?"
					),
					generate
				);
				return;
			}
			generate();
		},
	});

	dialog.show();
	update_invoice_generation_preview(frm, dialog);
}

function update_invoice_generation_preview(frm, dialog) {
	const through = dialog.get_value("generate_through");
	if (!through) return;

	const wrapper = dialog.fields_dict.preview_html.$wrapper;
	wrapper.html(`<div class="text-muted">${__("Loading invoice preview...")}</div>`);

	frappe.call({
		method: "rentals.tasks.daily.preview_invoice_generation",
		args: {
			lease_name: frm.doc.name,
			through_date: through,
		},
		callback(r) {
			const result = r.message || {};
			const periods = result.periods || [];
			if (!periods.length) {
				wrapper.html(
					`<div class="alert alert-info mt-3">${__(
						"No ungenerated billing periods are due through the selected date."
					)}</div>`
				);
				return;
			}

			const rows = periods
				.map((row) => {
					const status = row.existing_invoice
						? `<span class="text-muted">${__("Already generated")}</span>`
						: `<span class="text-success">${__("Will generate")}</span>`;
					return `
						<tr>
							<td>${frappe.datetime.str_to_user(row.billing_date)}</td>
							<td class="text-right">${format_currency(row.previous_balance, frm.doc.billing_currency)}</td>
							<td class="text-right">${format_currency(row.current_charges, frm.doc.billing_currency)}</td>
							<td class="text-right"><strong>${format_currency(
								row.projected_account_due,
								frm.doc.billing_currency
							)}</strong></td>
							<td>${status}</td>
						</tr>`;
				})
				.join("");

			const future_warning = result.has_future_periods
				? `<div class="alert alert-warning mb-3">${__(
						"This preview contains future billing periods. Generated invoices will use those future dates as their posting and due dates."
				  )}</div>`
				: "";

			wrapper.html(`
				<div class="mt-3">
					${future_warning}
					<p><strong>${__("Periods")}: ${result.period_count}</strong></p>
					<div class="table-responsive">
						<table class="table table-bordered table-sm">
							<thead>
								<tr>
									<th>${__("Billing Period")}</th>
									<th class="text-right">${__("Previous Balance")}</th>
									<th class="text-right">${__("Current Charges")}</th>
									<th class="text-right">${__("Projected Account Due")}</th>
									<th>${__("Status")}</th>
								</tr>
							</thead>
							<tbody>${rows}</tbody>
						</table>
					</div>
					<p class="text-muted small">${__(
						"Previous Balance is informational and is not added as another invoice item, so outstanding debt is not double-counted."
					)}</p>
				</div>`);
		},
		error() {
			wrapper.html(`<div class="alert alert-danger mt-3">${__("Unable to load invoice preview.")}</div>`);
		},
	});
}

function generate_invoices_through(frm, dialog, values) {
	dialog.disable_primary_action();
	frappe.call({
		method: "rentals.tasks.daily.generate_sales_invoices",
		args: {
			lease_name: frm.doc.name,
			through_date: values.generate_through,
			send_notifications: values.send_notifications ? 1 : 0,
			generation_source: "Manual",
		},
		callback(r) {
			const result = r.message || {};
			const invoices = result.invoices || [];
			dialog.hide();

			if (invoices.length) {
				const links = invoices
					.map((invoice) => `<a href="/app/sales-invoice/${encodeURIComponent(invoice)}" target="_blank">${invoice}</a>`)
					.join("<br>");
				frappe.msgprint({
					title: __("Invoices Generated"),
					indicator: "green",
					message: `${__(result.message || "Sales Invoice(s) generated successfully.")}<br><br>${links}`,
				});
			} else {
				frappe.msgprint(result.message || __("No invoices were created."));
			}
			frm.reload_doc();
		},
		error() {
			dialog.enable_primary_action();
		},
	});
}
