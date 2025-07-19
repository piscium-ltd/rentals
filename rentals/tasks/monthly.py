import frappe

def automated_impairment_check():
    # Fetch properties with required fields
    properties = frappe.get_all(
        "Property",
        filters={"enable_automated_impairment_check": 1},
        fields=["name", "occupancy_rate_threshold", "fair_value_decline_threshold"]
    )

    for prop in properties:
        occupancy_trigger = False
        fair_value_trigger = False

        # --- OCCUPANCY CHECK ---
        total_units = frappe.db.count("Unit", {"property": prop.name})
        if total_units > 0:
            occupied_units = frappe.db.count("Unit", {"property": prop.name, "status": "Occupied"})
            occupancy_rate = (occupied_units / total_units) * 100

            if occupancy_rate < prop.occupancy_rate_threshold:
                occupancy_trigger = True

        # --- FAIR VALUE CHECK ---
        valuation_history = frappe.get_all(
            "Valuation History",
            filters={"parent": prop.name},
            fields=["valuation_date", "valued_amount"],
            order_by="valuation_date desc",
            limit=2
        )

        if len(valuation_history) == 2:
            current_fair_value = valuation_history[0].valued_amount
            previous_fair_value = valuation_history[1].valued_amount

            if previous_fair_value > 0:  # avoid division by zero
                change_percentage = ((current_fair_value - previous_fair_value) / previous_fair_value) * 100
                
                if change_percentage <= -(prop.fair_value_decline_threshold):
                    fair_value_trigger = True

        # --- APPLY TRIGGER ---
        if occupancy_trigger or fair_value_trigger:
            frappe.db.set_value("Property", prop.name, "trigger_impairment_review", 1)
            create_impairment_todo(prop.name, occupancy_trigger, fair_value_trigger)

def create_impairment_todo(property_name, occupancy_trigger=False, fair_value_trigger=False):
    reasons = []
    if occupancy_trigger:
        reasons.append("Occupancy Rate below threshold")
    if fair_value_trigger:
        reasons.append("Fair Value decline exceeds threshold")

    todo = frappe.get_doc({
        "doctype": "ToDo",
        "description": f"Property {property_name}: " + ", ".join(reasons) + ". Review impairment.",
        "priority": "High",
        "status": "Open",
        "reference_type": "Property",
        "reference_name": property_name,
        "role":"Accounts User"
    })
    todo.insert(ignore_permissions=True)
