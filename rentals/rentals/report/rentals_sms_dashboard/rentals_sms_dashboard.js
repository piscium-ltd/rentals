// Copyright (c) 2026, Piscium Solutions LTD and contributors
// For license information, please see license.txt

frappe.query_reports['Rentals SMS Dashboard'] = {
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
			fieldname: 'sms_category',
			label: __('SMS Category'),
			fieldtype: 'Select',
			options: '\nTransactional\nReminder\nCampaign\nTest\nCallback\nOther',
		},
		{
			fieldname: 'status',
			label: __('Status'),
			fieldtype: 'Select',
			options: '\nPending\nQueued\nSubmitted\nSuccess\nSent\nBuffered\nDelivered\nFailed\nRejected\nInvalidPhoneNumber\nInsufficientBalance\nUserInBlacklist\nNotSent\nExpired\nUnknown\nOptedOut',
		},
		{
			fieldname: 'sms_campaign',
			label: __('SMS Campaign'),
			fieldtype: 'Link',
			options: 'Rentals SMS Campaign',
		},
		{
			fieldname: 'show_archived',
			label: __('Show Archived'),
			fieldtype: 'Check',
			default: 0,
		},
	],
};
