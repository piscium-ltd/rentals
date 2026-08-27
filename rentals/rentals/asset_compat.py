"""Small ERPNext Asset schema compatibility helpers.

ERPNext releases have used different field names for the acquisition amount on
Asset. Keep that version knowledge in one place so migrations and normal
Property provisioning make the same choice.
"""

ASSET_ACQUISITION_AMOUNT_FIELDS = (
    "net_purchase_amount",
    "gross_purchase_amount",
    "purchase_amount",
)

# Safe read-only fallbacks when recovering an already-recorded historical cost.
# ``total_asset_cost`` is intentionally not used when creating a new Asset,
# because ERPNext may derive it from the primary acquisition amount.
ASSET_RECORDED_COST_FIELDS = (*ASSET_ACQUISITION_AMOUNT_FIELDS, "total_asset_cost")


def supported_fields(meta, fieldnames):
    """Return field names that exist in the installed DocType schema."""
    return [fieldname for fieldname in fieldnames if meta.has_field(fieldname)]


def acquisition_amount_field(meta):
    """Return the preferred writable acquisition-amount field for this Asset schema."""
    return next(
        (fieldname for fieldname in ASSET_ACQUISITION_AMOUNT_FIELDS if meta.has_field(fieldname)),
        None,
    )
