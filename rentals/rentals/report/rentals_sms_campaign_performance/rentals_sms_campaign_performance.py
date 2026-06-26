# Copyright (c) 2026, Piscium Solutions LTD and contributors
# For license information, please see license.txt

"""Bulk SMS campaign performance report for Rentals."""

from __future__ import annotations

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

SENT_STATUSES = ("Submitted", "Success", "Sent", "Buffered", "Delivered")
FAILED_STATUSES = ("Failed", "Rejected", "InsufficientBalance", "UserInBlacklist", "Expired")
SKIPPED_STATUSES = ("InvalidPhoneNumber", "NotSent", "OptedOut")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters), None, get_chart(filters), get_summary(filters)


def _date_filters(filters):
	from_date = filters.get("from_date") or add_days(nowdate(), -90)
	to_date = filters.get("to_date") or nowdate()
	return getdate(from_date), getdate(to_date)


def _conditions(filters):
	from_date, to_date = _date_filters(filters)
	conditions = ["date(campaign.creation) between %(from_date)s and %(to_date)s"]
	params = {"from_date": from_date, "to_date": to_date}

	if filters.get("status"):
		conditions.append("campaign.status = %(status)s")
		params["status"] = filters.status

	if filters.get("target_type"):
		conditions.append("campaign.target_type = %(target_type)s")
		params["target_type"] = filters.target_type

	if filters.get("property"):
		conditions.append("campaign.property = %(property)s")
		params["property"] = filters.property

	if filters.get("landlord"):
		conditions.append("campaign.landlord = %(landlord)s")
		params["landlord"] = filters.landlord

	return " and ".join(conditions), params


def get_columns():
	return [
		{"label": "Campaign", "fieldname": "campaign", "fieldtype": "Link", "options": "Rentals SMS Campaign", "width": 180},
		{"label": "Title", "fieldname": "campaign_title", "fieldtype": "Data", "width": 220},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 110},
		{"label": "Target Type", "fieldname": "target_type", "fieldtype": "Data", "width": 190},
		{"label": "Property", "fieldname": "property", "fieldtype": "Link", "options": "Property", "width": 160},
		{"label": "Landlord", "fieldname": "landlord", "fieldtype": "Link", "options": "Landlord", "width": 160},
		{"label": "Created On", "fieldname": "creation", "fieldtype": "Datetime", "width": 160},
		{"label": "Sent On", "fieldname": "sent_on", "fieldtype": "Datetime", "width": 160},
		{"label": "Recipients", "fieldname": "total_recipients", "fieldtype": "Int", "width": 100},
		{"label": "Sent/Submitted", "fieldname": "total_sent", "fieldtype": "Int", "width": 110},
		{"label": "Delivered", "fieldname": "delivered", "fieldtype": "Int", "width": 100},
		{"label": "Failed", "fieldname": "failed", "fieldtype": "Int", "width": 90},
		{"label": "Skipped", "fieldname": "skipped", "fieldtype": "Int", "width": 90},
		{"label": "Delivery Rate %", "fieldname": "delivery_rate", "fieldtype": "Percent", "width": 120},
		{"label": "Failure Rate %", "fieldname": "failure_rate", "fieldtype": "Percent", "width": 120},
	]


def get_data(filters):
	where_clause, params = _conditions(filters)
	rows = frappe.db.sql(
		f"""
		select
			campaign.name as campaign,
			campaign.campaign_title,
			campaign.status,
			campaign.target_type,
			campaign.property,
			campaign.landlord,
			campaign.creation,
			campaign.sent_on,
			count(recipient.name) as recipient_rows,
			sum(case when recipient.status in %(sent_statuses)s then 1 else 0 end) as sent_count,
			sum(case when recipient.status = 'Delivered' then 1 else 0 end) as delivered_count,
			sum(case when recipient.status in %(failed_statuses)s then 1 else 0 end) as failed_count,
			sum(case when recipient.status in %(skipped_statuses)s then 1 else 0 end) as skipped_count
		from `tabRentals SMS Campaign` campaign
		left join `tabRentals SMS Campaign Recipient` recipient
			on recipient.parent = campaign.name
			and recipient.parenttype = 'Rentals SMS Campaign'
			and recipient.parentfield = 'recipients'
		where {where_clause}
		group by campaign.name
		order by campaign.creation desc
		""",
		{
			**params,
			"sent_statuses": SENT_STATUSES,
			"failed_statuses": FAILED_STATUSES,
			"skipped_statuses": SKIPPED_STATUSES,
		},
		as_dict=True,
	)

	data = []
	for row in rows:
		recipients = flt(row.recipient_rows)
		sent = flt(row.sent_count)
		delivered = flt(row.delivered_count)
		failed = flt(row.failed_count)
		row.total_recipients = int(recipients)
		row.total_sent = int(sent)
		row.delivered = int(delivered)
		row.failed = int(failed)
		row.skipped = int(row.skipped_count or 0)
		row.delivery_rate = round((delivered / recipients * 100) if recipients else 0, 2)
		row.failure_rate = round((failed / recipients * 100) if recipients else 0, 2)
		data.append(row)

	return data


def get_summary(filters):
	data = get_data(filters)
	total_campaigns = len(data)
	total_recipients = sum(row.total_recipients for row in data)
	total_sent = sum(row.total_sent for row in data)
	total_delivered = sum(row.delivered for row in data)
	total_failed = sum(row.failed for row in data)
	total_skipped = sum(row.skipped for row in data)
	delivery_rate = round((total_delivered / total_recipients * 100) if total_recipients else 0, 2)

	return [
		{"label": "Campaigns", "value": total_campaigns, "indicator": "Blue", "datatype": "Int"},
		{"label": "Recipients", "value": total_recipients, "indicator": "Blue", "datatype": "Int"},
		{"label": "Sent/Submitted", "value": total_sent, "indicator": "Green", "datatype": "Int"},
		{"label": "Delivered", "value": total_delivered, "indicator": "Green", "datatype": "Int"},
		{"label": "Failed", "value": total_failed, "indicator": "Red", "datatype": "Int"},
		{"label": "Skipped", "value": total_skipped, "indicator": "Orange", "datatype": "Int"},
		{"label": "Delivery Rate", "value": delivery_rate, "indicator": "Green", "datatype": "Percent"},
	]


def get_chart(filters):
	data = get_data(filters)[:20]
	labels = [row.campaign_title or row.campaign for row in reversed(data)]
	return {
		"data": {
			"labels": labels,
			"datasets": [
				{"name": "Delivered", "values": [int(row.delivered or 0) for row in reversed(data)]},
				{"name": "Failed", "values": [int(row.failed or 0) for row in reversed(data)]},
				{"name": "Skipped", "values": [int(row.skipped or 0) for row in reversed(data)]},
			],
		},
		"type": "bar",
	}
