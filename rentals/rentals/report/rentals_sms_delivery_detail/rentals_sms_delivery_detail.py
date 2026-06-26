# Copyright (c) 2026, Piscium Solutions LTD and contributors
# For license information, please see license.txt

"""Detailed SMS delivery report for Rentals."""

from __future__ import annotations

import frappe
from frappe.utils import add_days, getdate, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters), None, get_chart(filters), get_summary(filters)


def _date_filters(filters):
	from_date = filters.get("from_date") or add_days(nowdate(), -30)
	to_date = filters.get("to_date") or nowdate()
	return getdate(from_date), getdate(to_date)


def _conditions(filters):
	from_date, to_date = _date_filters(filters)
	conditions = ["date(log.creation) between %(from_date)s and %(to_date)s"]
	params = {"from_date": from_date, "to_date": to_date}

	if not filters.get("show_archived"):
		conditions.append("ifnull(log.archived, 0) = 0")

	if filters.get("status"):
		conditions.append("ifnull(log.status, '') = %(status)s")
		params["status"] = filters.status

	if filters.get("sms_category"):
		conditions.append("ifnull(log.sms_category, '') = %(sms_category)s")
		params["sms_category"] = filters.sms_category

	if filters.get("sms_campaign"):
		conditions.append("log.sms_campaign = %(sms_campaign)s")
		params["sms_campaign"] = filters.sms_campaign

	if filters.get("recipient_phone"):
		conditions.append("(log.recipient_phone like %(recipient_phone)s or log.normalized_phone like %(recipient_phone)s)")
		params["recipient_phone"] = f"%{filters.recipient_phone}%"

	if filters.get("reference_doctype"):
		conditions.append("log.reference_doctype = %(reference_doctype)s")
		params["reference_doctype"] = filters.reference_doctype

	if filters.get("reference_name"):
		conditions.append("log.reference_name = %(reference_name)s")
		params["reference_name"] = filters.reference_name

	return " and ".join(conditions), params


def get_columns():
	return [
		{"label": "Created On", "fieldname": "creation", "fieldtype": "Datetime", "width": 160},
		{"label": "SMS Log", "fieldname": "name", "fieldtype": "Link", "options": "Rentals SMS Log", "width": 160},
		{"label": "Recipient", "fieldname": "recipient_phone", "fieldtype": "Phone", "width": 140},
		{"label": "Normalized Phone", "fieldname": "normalized_phone", "fieldtype": "Data", "width": 140},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 120},
		{"label": "Category", "fieldname": "sms_category", "fieldtype": "Data", "width": 120},
		{"label": "Campaign", "fieldname": "sms_campaign", "fieldtype": "Link", "options": "Rentals SMS Campaign", "width": 170},
		{"label": "Reference Type", "fieldname": "reference_doctype", "fieldtype": "Data", "width": 130},
		{"label": "Reference", "fieldname": "reference_name", "fieldtype": "Dynamic Link", "options": "reference_doctype", "width": 160},
		{"label": "Provider Message ID", "fieldname": "provider_message_id", "fieldtype": "Data", "width": 180},
		{"label": "Provider Cost", "fieldname": "provider_cost", "fieldtype": "Data", "width": 120},
		{"label": "Delivery Status", "fieldname": "provider_delivery_status", "fieldtype": "Data", "width": 130},
		{"label": "Failure Reason", "fieldname": "failure_reason", "fieldtype": "Small Text", "width": 180},
		{"label": "Error", "fieldname": "error", "fieldtype": "Small Text", "width": 220},
		{"label": "Archived", "fieldname": "archived", "fieldtype": "Check", "width": 90},
		{"label": "Archived On", "fieldname": "archived_on", "fieldtype": "Datetime", "width": 160},
		{"label": "Message", "fieldname": "message", "fieldtype": "Small Text", "width": 320},
	]


def get_data(filters):
	where_clause, params = _conditions(filters)
	return frappe.db.sql(
		f"""
		select
			log.creation,
			log.name,
			log.recipient_phone,
			log.normalized_phone,
			coalesce(nullif(log.status, ''), 'Pending') as status,
			coalesce(nullif(log.sms_category, ''), 'Other') as sms_category,
			log.sms_campaign,
			log.reference_doctype,
			log.reference_name,
			log.provider_message_id,
			log.provider_cost,
			log.provider_delivery_status,
			log.failure_reason,
			log.error,
			log.archived,
			log.archived_on,
			log.message
		from `tabRentals SMS Log` log
		where {where_clause}
		order by log.creation desc
		limit 1000
		""",
		params,
		as_dict=True,
	)


def get_summary(filters):
	where_clause, params = _conditions(filters)
	rows = frappe.db.sql(
		f"""
		select
			coalesce(nullif(log.status, ''), 'Pending') as status,
			count(*) as count
		from `tabRentals SMS Log` log
		where {where_clause}
		group by coalesce(nullif(log.status, ''), 'Pending')
		""",
		params,
		as_dict=True,
	)

	indicator_map = {
		"Delivered": "Green",
		"Submitted": "Blue",
		"Success": "Green",
		"Sent": "Green",
		"Buffered": "Blue",
		"Failed": "Red",
		"Rejected": "Red",
		"InvalidPhoneNumber": "Red",
		"OptedOut": "Orange",
		"NotSent": "Orange",
	}
	return [
		{
			"label": row.status,
			"value": int(row.count or 0),
			"indicator": indicator_map.get(row.status, "Blue"),
			"datatype": "Int",
		}
		for row in rows
	]


def get_chart(filters):
	where_clause, params = _conditions(filters)
	rows = frappe.db.sql(
		f"""
		select
			coalesce(nullif(log.status, ''), 'Pending') as status,
			count(*) as count
		from `tabRentals SMS Log` log
		where {where_clause}
		group by coalesce(nullif(log.status, ''), 'Pending')
		order by count desc
		""",
		params,
		as_dict=True,
	)
	return {
		"data": {
			"labels": [row.status for row in rows],
			"datasets": [{"name": "SMS", "values": [int(row.count or 0) for row in rows]}],
		},
		"type": "donut",
	}
