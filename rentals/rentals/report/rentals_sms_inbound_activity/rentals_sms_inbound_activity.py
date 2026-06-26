# Copyright (c) 2026, Piscium Solutions LTD and contributors
# For license information, please see license.txt

"""Inbound SMS keyword activity report for Rentals."""

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

	if filters.get("action"):
		conditions.append("log.action = %(action)s")
		params["action"] = filters.action

	if filters.get("status"):
		conditions.append("log.status = %(status)s")
		params["status"] = filters.status

	if filters.get("keyword"):
		conditions.append("log.keyword = %(keyword)s")
		params["keyword"] = filters.keyword.upper()

	if filters.get("recipient_doctype"):
		conditions.append("log.recipient_doctype = %(recipient_doctype)s")
		params["recipient_doctype"] = filters.recipient_doctype

	if filters.get("recipient_name"):
		conditions.append("log.recipient_name = %(recipient_name)s")
		params["recipient_name"] = filters.recipient_name

	if filters.get("from_phone"):
		conditions.append("(log.from_phone like %(from_phone)s or log.normalized_phone like %(from_phone)s)")
		params["from_phone"] = f"%{filters.from_phone}%"

	return " and ".join(conditions), params


def get_columns():
	return [
		{"label": "Received On", "fieldname": "received_on", "fieldtype": "Datetime", "width": 160},
		{"label": "Inbound Log", "fieldname": "name", "fieldtype": "Link", "options": "Rentals SMS Inbound Log", "width": 170},
		{"label": "From", "fieldname": "from_phone", "fieldtype": "Phone", "width": 140},
		{"label": "Normalized Phone", "fieldname": "normalized_phone", "fieldtype": "Data", "width": 140},
		{"label": "Keyword", "fieldname": "keyword", "fieldtype": "Data", "width": 100},
		{"label": "Action", "fieldname": "action", "fieldtype": "Data", "width": 110},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 110},
		{"label": "Matched Type", "fieldname": "recipient_doctype", "fieldtype": "Data", "width": 130},
		{"label": "Matched Recipient", "fieldname": "recipient_name", "fieldtype": "Dynamic Link", "options": "recipient_doctype", "width": 170},
		{"label": "Matches", "fieldname": "matched_recipient_count", "fieldtype": "Int", "width": 90},
		{"label": "Provider Message ID", "fieldname": "provider_message_id", "fieldtype": "Data", "width": 170},
		{"label": "Network Code", "fieldname": "network_code", "fieldtype": "Data", "width": 120},
		{"label": "Error", "fieldname": "error", "fieldtype": "Small Text", "width": 220},
		{"label": "Archived", "fieldname": "archived", "fieldtype": "Check", "width": 90},
		{"label": "Archived On", "fieldname": "archived_on", "fieldtype": "Datetime", "width": 160},
		{"label": "Message", "fieldname": "message", "fieldtype": "Small Text", "width": 300},
	]


def get_data(filters):
	where_clause, params = _conditions(filters)
	return frappe.db.sql(
		f"""
		select
			coalesce(log.received_on, log.creation) as received_on,
			log.name,
			log.from_phone,
			log.normalized_phone,
			log.keyword,
			log.action,
			log.status,
			log.recipient_doctype,
			log.recipient_name,
			log.matched_recipient_count,
			log.provider_message_id,
			log.network_code,
			log.error,
			log.archived,
			log.archived_on,
			log.message
		from `tabRentals SMS Inbound Log` log
		where {where_clause}
		order by log.creation desc
		limit 1000
		""",
		params,
		as_dict=True,
	)


def get_summary(filters):
	where_clause, params = _conditions(filters)
	row = frappe.db.sql(
		f"""
		select
			count(*) as total,
			sum(case when log.action = 'OptOut' then 1 else 0 end) as opt_out,
			sum(case when log.action = 'OptIn' then 1 else 0 end) as opt_in,
			sum(case when log.action = 'Help' then 1 else 0 end) as help,
			sum(case when log.action = 'Unknown' then 1 else 0 end) as unknown,
			sum(case when log.status = 'Failed' then 1 else 0 end) as failed
		from `tabRentals SMS Inbound Log` log
		where {where_clause}
		""",
		params,
		as_dict=True,
	)[0]

	return [
		{"label": "Inbound SMS", "value": int(row.total or 0), "indicator": "Blue", "datatype": "Int"},
		{"label": "Opt-outs", "value": int(row.opt_out or 0), "indicator": "Orange", "datatype": "Int"},
		{"label": "Opt-ins", "value": int(row.opt_in or 0), "indicator": "Green", "datatype": "Int"},
		{"label": "Help", "value": int(row.help or 0), "indicator": "Blue", "datatype": "Int"},
		{"label": "Unknown", "value": int(row.unknown or 0), "indicator": "Gray", "datatype": "Int"},
		{"label": "Failed", "value": int(row.failed or 0), "indicator": "Red", "datatype": "Int"},
	]


def get_chart(filters):
	where_clause, params = _conditions(filters)
	rows = frappe.db.sql(
		f"""
		select
			coalesce(nullif(log.action, ''), 'Unknown') as action,
			count(*) as count
		from `tabRentals SMS Inbound Log` log
		where {where_clause}
		group by coalesce(nullif(log.action, ''), 'Unknown')
		order by count desc
		""",
		params,
		as_dict=True,
	)
	return {
		"data": {
			"labels": [row.action for row in rows],
			"datasets": [{"name": "Inbound SMS", "values": [int(row.count or 0) for row in rows]}],
		},
		"type": "donut",
	}
