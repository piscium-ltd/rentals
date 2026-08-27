import frappe
from frappe.utils import flt


def automated_impairment_check():
    """Flag properties whose configured quantitative thresholds are breached."""
    properties = frappe.get_all(
        "Property",
        filters={"enable_automated_impairment_check": 1},
        fields=[
            "name",
            "accounting_model",
            "occupancy_rate_threshold",
            "fair_value_decline_threshold",
        ],
    )

    for prop in properties:
        occupancy_trigger = _occupancy_threshold_breached(prop)
        fair_value_trigger = _fair_value_threshold_breached(prop)
        should_review = occupancy_trigger or fair_value_trigger

        frappe.db.set_value(
            "Property",
            prop.name,
            "trigger_impairment_review",
            1 if should_review else 0,
            update_modified=False,
        )

        if should_review:
            create_impairment_todo(prop.name, occupancy_trigger, fair_value_trigger)


def _occupancy_threshold_breached(prop):
    threshold = flt(prop.occupancy_rate_threshold)
    if threshold <= 0:
        return False

    total_units = frappe.db.count("Unit", {"property": prop.name})
    if total_units <= 0:
        return False

    occupied_units = frappe.db.count("Unit", {"property": prop.name, "status": "Occupied"})
    occupancy_rate = (occupied_units / total_units) * 100
    return occupancy_rate < threshold


def _fair_value_threshold_breached(prop):
    if prop.accounting_model != "Fair Value Model":
        return False

    threshold = flt(prop.fair_value_decline_threshold)
    if threshold <= 0:
        return False

    valuation_history = frappe.get_all(
        "Valuation History",
        filters={"parent": prop.name, "parenttype": "Property", "parentfield": "valuation_history"},
        fields=["valuation_date", "valued_amount"],
        order_by="valuation_date desc, idx desc",
        limit=2,
    )

    if len(valuation_history) < 2:
        return False

    current_fair_value = flt(valuation_history[0].valued_amount)
    previous_fair_value = flt(valuation_history[1].valued_amount)
    if previous_fair_value <= 0:
        return False

    change_percentage = ((current_fair_value - previous_fair_value) / previous_fair_value) * 100
    return change_percentage <= -threshold


def create_impairment_todo(property_name, occupancy_trigger=False, fair_value_trigger=False):
    """Create one open review task per Property instead of duplicating it every month."""
    existing = frappe.db.exists(
        "ToDo",
        {
            "reference_type": "Property",
            "reference_name": property_name,
            "status": "Open",
            "role": "Accounts User",
        },
    )
    if existing:
        return existing

    reasons = []
    if occupancy_trigger:
        reasons.append("Occupancy rate below configured threshold")
    if fair_value_trigger:
        reasons.append("Fair value decline exceeds configured threshold")

    todo = frappe.get_doc(
        {
            "doctype": "ToDo",
            "description": f"Property {property_name}: " + ", ".join(reasons) + ". Review impairment.",
            "priority": "High",
            "status": "Open",
            "reference_type": "Property",
            "reference_name": property_name,
            "role": "Accounts User",
        }
    )
    todo.insert(ignore_permissions=True)
    return todo.name
