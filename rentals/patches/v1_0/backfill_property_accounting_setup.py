import frappe
from frappe.utils import flt, getdate


DEFAULT_USEFUL_LIFE_YEARS = 40


def execute():
    """Backfill new Property accounting/setup fields without inventing acquisition costs."""
    if not frappe.db.exists("DocType", "Property"):
        return

    properties = frappe.get_all(
        "Property",
        fields=[
            "name",
            "creation",
            "asset",
            "location",
            "rental_location",
            "sub_location",
            "ward",
            "accounting_model",
            "current_fair_value",
            "acquisition_cost",
            "acquisition_date",
            "available_for_use_date",
            "calculate_depreciation",
            "useful_life_years",
            "depreciation_frequency",
            "residual_value",
        ],
    )

    for prop in properties:
        values = {}
        asset = _get_asset_values(prop.asset)

        _backfill_geography(prop, values)
        _backfill_dates(prop, asset, values)
        _backfill_acquisition_cost(prop, asset, values)
        _backfill_depreciation(prop, asset, values)
        _backfill_setup_status(prop, asset, values)

        if values:
            frappe.db.set_value("Property", prop.name, values, update_modified=False)


def _get_asset_values(asset_name):
    if not asset_name or not frappe.db.exists("Asset", asset_name):
        return None

    fields = [
        "name",
        "docstatus",
        "purchase_date",
        "available_for_use_date",
        "net_purchase_amount",
        "calculate_depreciation",
    ]
    asset_meta = frappe.get_meta("Asset")
    if asset_meta.has_field("gross_purchase_amount"):
        fields.append("gross_purchase_amount")

    asset = frappe.db.get_value("Asset", asset_name, fields, as_dict=True)
    if not asset:
        return None

    if asset.calculate_depreciation:
        finance_book = frappe.db.get_value(
            "Asset Finance Book",
            {"parent": asset_name, "parenttype": "Asset", "parentfield": "finance_books"},
            [
                "frequency_of_depreciation",
                "total_number_of_depreciations",
                "expected_value_after_useful_life",
            ],
            as_dict=True,
        )
        asset.finance_book = finance_book

    return asset


def _backfill_geography(prop, values):
    if prop.rental_location:
        return

    if prop.sub_location:
        location = frappe.db.get_value("Sub Location", prop.sub_location, "location")
        if location:
            values["rental_location"] = location
            return

    if not prop.location:
        return

    # Legacy Property.location pointed to ERPNext Asset Location. Only map it
    # automatically when an unambiguous Rentals Location Name already exists.
    asset_location_name = frappe.db.get_value("Location", prop.location, "location_name") or prop.location
    filters = {"location": asset_location_name}
    if prop.ward:
        filters["ward"] = prop.ward

    rental_location = frappe.db.get_value("Location Name", filters, "name")
    if rental_location:
        values["rental_location"] = rental_location


def _backfill_dates(prop, asset, values):
    acquisition_date = prop.acquisition_date
    if not acquisition_date:
        acquisition_date = asset.purchase_date if asset and asset.purchase_date else getdate(prop.creation)
        values["acquisition_date"] = acquisition_date

    if not prop.available_for_use_date:
        available_date = (
            asset.available_for_use_date if asset and asset.available_for_use_date else acquisition_date
        )
        values["available_for_use_date"] = available_date


def _backfill_acquisition_cost(prop, asset, values):
    if flt(prop.acquisition_cost) > 0:
        return

    if not asset:
        return

    amount = flt(asset.net_purchase_amount)
    if amount <= 0 and asset.get("gross_purchase_amount") is not None:
        amount = flt(asset.gross_purchase_amount)

    if amount > 0:
        values["acquisition_cost"] = amount


def _backfill_depreciation(prop, asset, values):
    if prop.accounting_model == "Fair Value Model":
        values["calculate_depreciation"] = 0
        return

    calculate_depreciation = int(asset.calculate_depreciation) if asset else int(prop.calculate_depreciation or 0)
    values["calculate_depreciation"] = calculate_depreciation

    if not calculate_depreciation:
        return

    finance_book = asset.get("finance_book") if asset else None
    frequency_months = int(finance_book.frequency_of_depreciation) if finance_book else 12
    total_depreciations = int(finance_book.total_number_of_depreciations) if finance_book else 0

    values["depreciation_frequency"] = _frequency_label(frequency_months)

    if flt(prop.useful_life_years) <= 0:
        useful_life = (
            (frequency_months * total_depreciations) / 12
            if total_depreciations > 0
            else DEFAULT_USEFUL_LIFE_YEARS
        )
        values["useful_life_years"] = useful_life

    if finance_book:
        old_residual_value = flt(finance_book.expected_value_after_useful_life)
        if old_residual_value and flt(prop.residual_value) == 0:
            values["residual_value"] = old_residual_value


def _backfill_setup_status(prop, asset, values):
    if asset and asset.docstatus == 1:
        values["setup_status"] = "Completed"
        values["setup_error"] = None
        return

    values["setup_status"] = "Failed"
    if asset and asset.docstatus == 0:
        values["setup_error"] = (
            "A draft ERPNext Asset is linked from an earlier setup attempt. "
            "Review the Property inputs and use Actions → Retry Asset Setup."
        )
    else:
        values["setup_error"] = (
            "No submitted ERPNext Asset is linked to this existing Property. "
            "Enter or verify Acquisition Cost and Location, then use Actions → Retry Asset Setup."
        )


def _frequency_label(months):
    return {
        1: "Monthly",
        3: "Quarterly",
        6: "Semi-Annual",
        12: "Annual",
    }.get(months, "Annual")
