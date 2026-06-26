// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.query_reports['Rentals SMS Campaign Performance'] = {
	filters: [
		{
			fieldname: 'from_date',
			label: __('From Date'),
			fieldtype: 'Date',
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -90),
			reqd: 1,
		},
		{
			fieldname: 'to_date',
			label: __('To Date'),
			fieldtype: 'Date',
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: 'status',
			label: __('Campaign Status'),
			fieldtype: 'Select',
			options: '\nDraft\nQueued\nSending\nCompleted\nFailed\nCancelled',
		},
		{
			fieldname: 'target_type',
			label: __('Target Type'),
			fieldtype: 'Select',
			options: '\nAll Active Tenants\nTenants by Property\nTenants by Landlord\nTenants with Active Leases\nTenants with Outstanding Invoices\nManual Numbers',
		},
		{
			fieldname: 'property',
			label: __('Property'),
			fieldtype: 'Link',
			options: 'Property',
		},
		{
			fieldname: 'landlord',
			label: __('Landlord'),
			fieldtype: 'Link',
			options: 'Landlord',
		},
	],
};
