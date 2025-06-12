// Copyright (c) 2025, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.ui.form.on("Lease Agreement", {
	refresh(frm) {
		frm.set_query("property", () => ({
			filters: {
				landlord: frm.doc.landlord,
			},
		}));
		frm.set_query("unit", () => ({
			filters: {
				property: frm.doc.property,
			},
		}));

		frm.set_query("service", "chargeable_services", () => ({
			filters: {
				item_group: "Rental Chargeable Services",
			},
		}));

		if (frm.doc.docstatus === 1) {
			// only show for submitted leases
			frm.add_custom_button(__("Generate Invoice"), function () {
				frappe.call({
					method: "rentals.tasks.daily.generate_sales_invoices",
					args: {
						lease_name: frm.doc.name,
						override_billing_date: true,
					},
					callback: function (r) {
						if (r.message && r.message.invoices && r.message.invoices.length > 0) {
							let links = r.message.invoices
								.map((inv) => {
									let invoice_url = `/app/sales-invoice/${inv}`;
									// Automatically open the invoice in a new tab
									window.open(invoice_url, "_blank");
									return `<a href="${invoice_url}" target="_blank">${inv}</a>`;
								})
								.join("<br>");
							frappe.msgprint({
								title: __("Sales Invoice(s) Created"),
								indicator: "green",
								message: __(r.message.message + "<br><br>" + links),
							});
							frm.reload_doc();
						} else {
							frappe.msgprint(r.message.message || __("No invoices created."));
						}
					},
					error: function () {
						frappe.msgprint(__("Error generating sales invoice."));
					},
				});
			});
		}

		calculate_grand_total(frm);
	},
});

frappe.ui.form.on("Chargeable Services", {
	rate(frm, cdt, cdn) {
		calculate_grand_total(frm);
	},
	chargeable_services_add(frm) {
		calculate_grand_total(frm);
	},
	chargeable_services_remove(frm) {
		calculate_grand_total(frm);
	},
	billing_cycle: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];
		let today = frappe.datetime.get_today();
		let next_date;

		if (row.billing_cycle === "Once") {
			next_date = today;
		} else if (row.billing_cycle === "Daily") {
			next_date = frappe.datetime.add_days(today, 1);
		} else if (row.billing_cycle === "Weekly") {
			next_date = frappe.datetime.add_days(today, 7);
		} else if (row.billing_cycle === "Monthly") {
			next_date = frappe.datetime.add_months(today, 1);
		} else if (row.billing_cycle === "Annually") {
			next_date = frappe.datetime.add_years(today, 1);
		}

		frappe.model.set_value(cdt, cdn, "billing_date", next_date);
	},
});

function calculate_grand_total(frm) {
	let total = 0;
	(frm.doc.chargeable_services || []).forEach((row) => {
		total += flt(row.rate);
	});
	frm.set_value("grand_total", total);
}
