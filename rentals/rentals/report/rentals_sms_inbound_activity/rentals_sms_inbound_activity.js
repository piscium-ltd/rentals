// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.query_reports['Rentals SMS Inbound Activity'] = {
	filters: [
		{
			fieldname: 'from_date',
			label: __('From Date'),
			fieldtype: 'Date',
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -30),
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
			fieldname: 'action',
			label: __('Action'),
			fieldtype: 'Select',
			options: '\nOptOut\nOptIn\nHelp\nUnknown\nIgnored\nFailed',
		},
		{
			fieldname: 'status',
			label: __('Status'),
			fieldtype: 'Select',
			options: '\nReceived\nProcessed\nIgnored\nFailed',
		},
		{
			fieldname: 'keyword',
			label: __('Keyword'),
			fieldtype: 'Data',
		},
		{
			fieldname: 'from_phone',
			label: __('From Phone'),
			fieldtype: 'Data',
		},
		{
			fieldname: 'recipient_doctype',
			label: __('Matched Type'),
			fieldtype: 'Link',
			options: 'DocType',
		},
		{
			fieldname: 'recipient_name',
			label: __('Matched Recipient'),
			fieldtype: 'Dynamic Link',
			options: 'recipient_doctype',
		},
		{
			fieldname: 'show_archived',
			label: __('Show Archived'),
			fieldtype: 'Check',
			default: 0,
		},
	],
};
