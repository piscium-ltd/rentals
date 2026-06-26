# Copyright (c) 2026, Piscium Solutions LTD and contributors
# For license information, please see license.txt

"""SMS dashboard report for Rentals."""

from __future__ import annotations

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

SUCCESS_STATUSES = ("Submitted", "Success", "Sent", "Buffered", "Delivered")
FAILED_STATUSES = (
	"Failed",
	"Rejected",
	"InvalidPhoneNumber",
	"InsufficientBalance",
	"UserInBlacklist",
	"Expired",
)
SKIPPED_STATUSES = ("NotSent", "OptedOut")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_data(filters)
	chart = get_chart(filters)
	summary = get_summary(filters)
	return columns, data, None, chart, summary


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

	if filters.get("sms_category"):
		conditions.append("ifnull(log.sms_category, '') = %(sms_category)s")
		params["sms_category"] = filters.sms_category

	if filters.get("status"):
		conditions.append("ifnull(log.status, '') = %(status)s")
		params["status"] = filters.status

	if filters.get("sms_campaign"):
		conditions.append("log.sms_campaign = %(sms_campaign)s")
		params["sms_campaign"] = filters.sms_campaign

	return " and ".join(conditions), params


def get_columns():
	return [
		{"label": "Date", "fieldname": "date", "fieldtype": "Date", "width": 110},
		{"label": "SMS Category", "fieldname": "sms_category", "fieldtype": "Data", "width": 130},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 130},
		{"label": "Campaign", "fieldname": "sms_campaign", "fieldtype": "Link", "options": "Rentals SMS Campaign", "width": 180},
		{"label": "Count", "fieldname": "count", "fieldtype": "Int", "width": 90},
	]


def get_data(filters):
	where_clause, params = _conditions(filters)
	return frappe.db.sql(
		f"""
		select
			date(log.creation) as date,
			coalesce(nullif(log.sms_category, ''), 'Other') as sms_category,
			coalesce(nullif(log.status, ''), 'Pending') as status,
			log.sms_campaign as sms_campaign,
			count(*) as count
		from `tabRentals SMS Log` log
		where {where_clause}
		group by date(log.creation), coalesce(nullif(log.sms_category, ''), 'Other'),
			coalesce(nullif(log.status, ''), 'Pending'), log.sms_campaign
		order by date(log.creation) desc, sms_category asc, status asc, sms_campaign asc
		""",
		params,
		as_dict=True,
	)


def get_summary(filters):
	where_clause, params = _conditions(filters)
	row = frappe.db.sql(
		f"""
		select
			count(*) as total_sms,
			sum(case when log.status in %(success_statuses)s then 1 else 0 end) as successful_sms,
			sum(case when log.status = 'Delivered' then 1 else 0 end) as delivered_sms,
			sum(case when log.status in %(failed_statuses)s then 1 else 0 end) as failed_sms,
			sum(case when log.status in %(skipped_statuses)s then 1 else 0 end) as skipped_sms
		from `tabRentals SMS Log` log
		where {where_clause}
		""",
		{
			**params,
			"success_statuses": SUCCESS_STATUSES,
			"failed_statuses": FAILED_STATUSES,
			"skipped_statuses": SKIPPED_STATUSES,
		},
		as_dict=True,
	)[0]

	total = flt(row.get("total_sms"))
	delivered = flt(row.get("delivered_sms"))
	delivery_rate = (delivered / total * 100) if total else 0

	return [
		{"label": "Total SMS", "value": int(total), "indicator": "Blue", "datatype": "Int"},
		{"label": "Successful/Submitted", "value": int(row.get("successful_sms") or 0), "indicator": "Green", "datatype": "Int"},
		{"label": "Delivered", "value": int(delivered), "indicator": "Green", "datatype": "Int"},
		{"label": "Failed", "value": int(row.get("failed_sms") or 0), "indicator": "Red", "datatype": "Int"},
		{"label": "Skipped", "value": int(row.get("skipped_sms") or 0), "indicator": "Orange", "datatype": "Int"},
		{"label": "Delivery Rate", "value": round(delivery_rate, 2), "indicator": "Green", "datatype": "Percent"},
	]


def get_chart(filters):
	where_clause, params = _conditions(filters)
	rows = frappe.db.sql(
		f"""
		select
			date(log.creation) as date,
			sum(case when log.status in %(success_statuses)s then 1 else 0 end) as successful_sms,
			sum(case when log.status = 'Delivered' then 1 else 0 end) as delivered_sms,
			sum(case when log.status in %(failed_statuses)s then 1 else 0 end) as failed_sms,
			sum(case when log.status in %(skipped_statuses)s then 1 else 0 end) as skipped_sms
		from `tabRentals SMS Log` log
		where {where_clause}
		group by date(log.creation)
		order by date(log.creation) asc
		""",
		{
			**params,
			"success_statuses": SUCCESS_STATUSES,
			"failed_statuses": FAILED_STATUSES,
			"skipped_statuses": SKIPPED_STATUSES,
		},
		as_dict=True,
	)

	return {
		"data": {
			"labels": [str(row.date) for row in rows],
			"datasets": [
				{"name": "Submitted/Sent", "values": [int(row.successful_sms or 0) for row in rows]},
				{"name": "Delivered", "values": [int(row.delivered_sms or 0) for row in rows]},
				{"name": "Failed", "values": [int(row.failed_sms or 0) for row in rows]},
				{"name": "Skipped", "values": [int(row.skipped_sms or 0) for row in rows]},
			],
		},
		"type": "line",
	}
