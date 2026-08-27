# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import math

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_last_day, getdate, now, nowdate


ASSET_SETUP_QUEUE = "long"
ASSET_SETUP_METHOD = "rentals.rentals.doctype.property.property.provision_property_asset"
ASSET_ITEM_CODE = "Rental Property"
ASSET_CATEGORY = "Investment Property"
DEPRECIATION_FREQUENCY_MONTHS = {
    "Monthly": 1,
    "Quarterly": 3,
    "Semi-Annual": 6,
    "Annual": 12,
}


class Property(Document):
    def validate(self):
        """Validate accounting inputs and keep derived valuation fields in sync."""
        self._validate_landlord_ready()
        self._validate_accounting_inputs()
        self._sync_current_fair_value()

    def after_insert(self):
        """Save quickly, then provision the ERPNext Asset in a background worker."""
        self.db_set("setup_status", "Pending", update_modified=False)
        self.db_set("setup_error", None, update_modified=False)
        self.db_set("setup_completed_on", None, update_modified=False)
        self._enqueue_asset_setup()

    def on_update(self):
        """Post one fair-value adjustment only when the carrying value actually changes."""
        if self.accounting_model != "Fair Value Model" or not self.asset:
            return

        old_doc = self.get_doc_before_save()
        if not old_doc:
            return

        old_value = flt(old_doc.current_fair_value)
        new_value = flt(self.current_fair_value)
        change_in_value = new_value - old_value

        if abs(change_in_value) < 0.01:
            return

        self._create_fair_value_adjustment(
            new_value=new_value,
            adjustment_date=self.last_valuation_date or nowdate(),
        )

    # ---------------------------------------------------------------------
    # Validation and derived fields
    # ---------------------------------------------------------------------

    def _validate_landlord_ready(self):
        landlord = frappe.db.get_value(
            "Landlord",
            self.landlord,
            ["company", "status", "setup_status"],
            as_dict=True,
        )

        if not landlord:
            frappe.throw(_("Landlord {0} was not found.").format(self.landlord))

        if landlord.status == "Inactive":
            frappe.throw(
                _("Landlord {0} is inactive. Choose an active landlord before saving the property.").format(
                    self.landlord
                )
            )

        if not self.rental_location and (self.is_new() or not self.asset):
            frappe.throw(_("Location is required before the Property Asset can be set up."))

        if not landlord.company:
            if landlord.setup_status in {"Pending", "In Progress"}:
                frappe.throw(
                    _(
                        "Landlord {0} is still being set up. Wait for Landlord Setup Status to become "
                        "Completed, then save the property again."
                    ).format(self.landlord)
                )

            if landlord.setup_status == "Failed":
                frappe.throw(
                    _(
                        "Landlord {0} setup failed, so a Company is not available for this property. "
                        "Open the Landlord and use Actions → Retry Setup first."
                    ).format(self.landlord)
                )

            frappe.throw(
                _(
                    "Landlord {0} does not have a linked Company. Complete the landlord setup before "
                    "creating a property."
                ).format(self.landlord)
            )


    def _validate_accounting_inputs(self):
        acquisition_cost = flt(self.acquisition_cost)
        if acquisition_cost <= 0:
            frappe.throw(
                _(
                    "Acquisition Cost must be greater than zero. It is used as the ERPNext Asset "
                    "Net Purchase Amount for both accounting models."
                )
            )

        if not self.acquisition_date:
            frappe.throw(_("Acquisition Date is required."))

        if not self.available_for_use_date:
            frappe.throw(_("Available for Use Date is required."))

        if getdate(self.available_for_use_date) < getdate(self.acquisition_date):
            frappe.throw(_("Available for Use Date cannot be before the Acquisition Date."))

        if self.accounting_model == "Fair Value Model":
            self.calculate_depreciation = 0
            self._validate_valuation_history()
            return

        # Cost model does not use the fair-value child table for carrying value.
        self.current_fair_value = None
        self.last_valuation_date = None

        if not cint(self.calculate_depreciation):
            return

        useful_life_years = flt(self.useful_life_years)
        if useful_life_years <= 0:
            frappe.throw(_("Useful Life (Years) must be greater than zero when depreciation is enabled."))

        if self.depreciation_frequency not in DEPRECIATION_FREQUENCY_MONTHS:
            frappe.throw(_("Choose a valid Depreciation Frequency."))

        residual_value = flt(self.residual_value)
        if residual_value < 0:
            frappe.throw(_("Residual Value cannot be negative."))
        if residual_value >= acquisition_cost:
            frappe.throw(_("Residual Value must be less than Acquisition Cost."))

    def _validate_valuation_history(self):
        if not self.valuation_history:
            frappe.throw(
                _(
                    "Add at least one Valuation History row for the Fair Value Model. "
                    "The latest valuation becomes the Current Fair Value."
                )
            )

        seen_dates = set()
        for row in self.valuation_history:
            if not row.valuation_date:
                frappe.throw(_("Every valuation row must have a Valuation Date."))

            valuation_date = getdate(row.valuation_date)
            if valuation_date > getdate(nowdate()):
                frappe.throw(_("Valuation Date cannot be in the future."))
            if self.acquisition_date and valuation_date < getdate(self.acquisition_date):
                frappe.throw(
                    _("Valuation Date cannot be before the Acquisition Date ({0}).").format(
                        self.acquisition_date
                    )
                )

            if valuation_date in seen_dates:
                frappe.throw(
                    _("Only one valuation is allowed per date. Duplicate date: {0}.").format(
                        valuation_date
                    )
                )
            seen_dates.add(valuation_date)

            if flt(row.valued_amount) <= 0:
                frappe.throw(_("Valued Amount must be greater than zero in every valuation row."))

    def _sync_current_fair_value(self):
        if self.accounting_model != "Fair Value Model" or not self.valuation_history:
            return

        latest = max(self.valuation_history, key=lambda row: getdate(row.valuation_date))
        self.current_fair_value = flt(latest.valued_amount)
        self.last_valuation_date = latest.valuation_date

    # ---------------------------------------------------------------------
    # Background Asset provisioning
    # ---------------------------------------------------------------------

    def _enqueue_asset_setup(self):
        frappe.enqueue(
            ASSET_SETUP_METHOD,
            queue=ASSET_SETUP_QUEUE,
            enqueue_after_commit=True,
            job_id=f"property-asset-setup-{self.name}",
            deduplicate=True,
            property_name=self.name,
        )

    def _provision_asset(self):
        """Idempotently create and link the ERPNext Asset for this Property."""
        if self.asset and frappe.db.exists("Asset", self.asset):
            linked_asset = frappe.get_doc("Asset", self.asset)
            if linked_asset.docstatus == 1:
                self._align_asset_to_fair_value()
                self._mark_setup_completed()
                return self.asset

        self.db_set("setup_status", "In Progress", update_modified=False)
        self.db_set("setup_error", None, update_modified=False)

        company = frappe.db.get_value("Landlord", self.landlord, "company")
        if not company:
            frappe.throw(
                _(
                    "Landlord {0} does not have a linked Company. Complete landlord setup before "
                    "retrying property asset setup."
                ).format(self.landlord)
            )

        asset_category = self.ensure_company_in_asset_category(company)
        asset_location = self._ensure_asset_location()
        self.db_set("location", asset_location, update_modified=False)
        self.location = asset_location

        existing_asset = frappe.db.get_value(
            "Asset",
            {
                "asset_name": self.name,
                "item_code": ASSET_ITEM_CODE,
                "company": company,
                "docstatus": ["!=", 2],
            },
            "name",
        )

        asset_payload = self._build_asset_payload(
            company=company,
            asset_category=asset_category,
            asset_location=asset_location,
        )

        if existing_asset:
            asset = frappe.get_doc("Asset", existing_asset)
            if asset.docstatus == 0:
                # A previous attempt may have inserted a draft before failing on
                # submission. Repair it from the current Property values and retry.
                for fieldname, value in asset_payload.items():
                    if fieldname in {"doctype", "finance_books"}:
                        continue
                    if asset.meta.has_field(fieldname):
                        asset.set(fieldname, value)
                asset.set("finance_books", asset_payload.get("finance_books", []))
                asset.save(ignore_permissions=True)
                asset.submit()

            self.db_set("asset", asset.name, update_modified=False)
            self.asset = asset.name
            self._align_asset_to_fair_value()
            self._mark_setup_completed()
            return asset.name

        asset = frappe.get_doc(asset_payload)
        asset.insert(ignore_permissions=True)
        asset.submit()

        self.db_set("asset", asset.name, update_modified=False)
        self.asset = asset.name
        self._align_asset_to_fair_value()
        self._mark_setup_completed()
        return asset.name

    def _build_asset_payload(self, *, company, asset_category, asset_location):
        """Build a version-tolerant ERPNext Asset payload."""
        amount = flt(self.acquisition_cost)
        asset_meta = frappe.get_meta("Asset")

        payload = {
            "doctype": "Asset",
            "item_code": ASSET_ITEM_CODE,
            "asset_name": self.name,
            "asset_category": asset_category,
            "company": company,
            "location": asset_location,
            "purchase_date": self.acquisition_date,
            "available_for_use_date": self.available_for_use_date,
            "net_purchase_amount": amount,
            "asset_quantity": 1,
        }

        # ERPNext v16+ uses asset_type; older supported benches used is_existing_asset.
        if asset_meta.has_field("asset_type"):
            payload["asset_type"] = "Existing Asset"
        elif asset_meta.has_field("is_existing_asset"):
            payload["is_existing_asset"] = 1

        # Keep compatibility with older Asset schemas while always populating the
        # modern mandatory Net Purchase Amount that caused the original failure.
        if asset_meta.has_field("gross_purchase_amount"):
            payload["gross_purchase_amount"] = amount

        if self.accounting_model == "Cost Model" and cint(self.calculate_depreciation):
            frequency = self._get_depreciation_frequency_months()
            payload["calculate_depreciation"] = 1
            payload["finance_books"] = [
                {
                    "depreciation_method": "Straight Line",
                    "frequency_of_depreciation": frequency,
                    "total_number_of_depreciations": self._get_total_depreciations(frequency),
                    "depreciation_start_date": get_last_day(self.available_for_use_date),
                    "expected_value_after_useful_life": flt(self.residual_value),
                }
            ]
        else:
            payload["calculate_depreciation"] = 0

        return payload

    def _get_depreciation_frequency_months(self):
        return DEPRECIATION_FREQUENCY_MONTHS.get(self.depreciation_frequency, 12)

    def _get_total_depreciations(self, frequency_months):
        total_months = flt(self.useful_life_years) * 12
        return max(1, math.ceil(total_months / frequency_months))

    def _ensure_asset_location(self):
        """Create a dedicated ERPNext Asset Location for the physical property site."""
        location_name = self.name
        existing = frappe.db.get_value("Location", {"location_name": location_name}, "name")
        if existing:
            return existing

        location = frappe.get_doc(
            {
                "doctype": "Location",
                "location_name": location_name,
                "is_group": 0,
            }
        )
        location.insert(ignore_permissions=True)
        return location.name

    def _mark_setup_completed(self):
        self.db_set("setup_completed_on", now(), update_modified=False)
        self.db_set("setup_status", "Completed", update_modified=False)
        self.db_set("setup_error", None, update_modified=False)

    # ---------------------------------------------------------------------
    # Fair value accounting
    # ---------------------------------------------------------------------

    def _align_asset_to_fair_value(self):
        """Align a newly linked Fair Value Model Asset with its latest valuation."""
        if self.accounting_model != "Fair Value Model" or not self.asset:
            return None

        target_value = flt(self.current_fair_value)
        if target_value <= 0:
            return None

        return self._create_fair_value_adjustment(
            new_value=target_value,
            adjustment_date=self.last_valuation_date or self.available_for_use_date or nowdate(),
        )

    def _create_fair_value_adjustment(self, *, new_value, adjustment_date):
        """Use ERPNext Asset Value Adjustment so Asset and ledger stay synchronized."""
        if not self.asset or not frappe.db.exists("Asset", self.asset):
            return None

        current_asset_value = flt(
            frappe.db.get_value("Asset", self.asset, "value_after_depreciation")
        )
        new_value = flt(new_value)
        if abs(new_value - current_asset_value) < 0.01:
            return None

        company = frappe.db.get_value("Landlord", self.landlord, "company")
        if not company:
            frappe.throw(_("Cannot post fair value adjustment because the Landlord Company is missing."))

        if new_value > current_asset_value:
            difference_account = self._get_or_create_account(
                company=company,
                account_name="Investment Property Fair Value Gain",
                root_type="Income",
                report_type="Profit and Loss",
                account_type=None,
                preferred_parent_names=["Indirect Income", "Income", "Direct Income"],
            )
        else:
            difference_account = self._get_or_create_account(
                company=company,
                account_name="Investment Property Fair Value Loss",
                root_type="Expense",
                report_type="Profit and Loss",
                account_type=None,
                preferred_parent_names=["Indirect Expenses", "Expenses", "Direct Expenses"],
            )

        company_defaults = frappe.db.get_value(
            "Company",
            company,
            ["cost_center", "depreciation_cost_center"],
            as_dict=True,
        )
        cost_center = None
        if company_defaults:
            cost_center = company_defaults.cost_center or company_defaults.depreciation_cost_center

        adjustment = frappe.get_doc(
            {
                "doctype": "Asset Value Adjustment",
                "asset": self.asset,
                "company": company,
                "date": adjustment_date,
                "new_asset_value": new_value,
                "difference_account": difference_account,
                "cost_center": cost_center,
            }
        )
        adjustment.flags.ignore_permissions = True
        adjustment.insert()
        adjustment.submit()
        return adjustment.name

    # ---------------------------------------------------------------------
    # Asset category/account provisioning
    # ---------------------------------------------------------------------

    def ensure_company_in_asset_category(self, company):
        """Ensure Asset Category 'Investment Property' has valid company accounts."""
        category = self._get_or_create_asset_category(ASSET_CATEGORY)

        for acc in category.accounts:
            if acc.company_name == company:
                self._repair_asset_category_account_row(acc, company)
                category.save(ignore_permissions=True)
                return category.name

        fixed_asset_account = self._get_or_create_account(
            company=company,
            account_name="Buildings",
            root_type="Asset",
            report_type="Balance Sheet",
            account_type="Fixed Asset",
            preferred_parent_names=["Fixed Assets", "Application of Funds (Assets)", "Assets"],
        )

        accumulated_depreciation_account = self._get_or_create_account(
            company=company,
            account_name="Accumulated Depreciation",
            root_type="Asset",
            report_type="Balance Sheet",
            account_type="Accumulated Depreciation",
            preferred_parent_names=["Fixed Assets", "Application of Funds (Assets)", "Assets"],
        )

        depreciation_expense_account = self._get_or_create_account(
            company=company,
            account_name="Depreciation",
            root_type="Expense",
            report_type="Profit and Loss",
            account_type="Depreciation",
            preferred_parent_names=["Indirect Expenses", "Expenses", "Direct Expenses"],
        )

        capital_work_in_progress_account = self._get_or_create_account(
            company=company,
            account_name="CWIP Account",
            root_type="Asset",
            report_type="Balance Sheet",
            account_type="Capital Work in Progress",
            preferred_parent_names=["Fixed Assets", "Application of Funds (Assets)", "Assets"],
        )

        category.append(
            "accounts",
            {
                "company_name": company,
                "fixed_asset_account": fixed_asset_account,
                "accumulated_depreciation_account": accumulated_depreciation_account,
                "depreciation_expense_account": depreciation_expense_account,
                "capital_work_in_progress_account": capital_work_in_progress_account,
            },
        )
        if category.is_new():
            category.insert(ignore_permissions=True)
        else:
            category.save(ignore_permissions=True)
        return category.name

    def _repair_asset_category_account_row(self, row, company):
        """Repair an existing Asset Category row if any linked account is missing."""
        if not row.fixed_asset_account or not frappe.db.exists("Account", row.fixed_asset_account):
            row.fixed_asset_account = self._get_or_create_account(
                company=company,
                account_name="Buildings",
                root_type="Asset",
                report_type="Balance Sheet",
                account_type="Fixed Asset",
                preferred_parent_names=["Fixed Assets", "Application of Funds (Assets)", "Assets"],
            )

        if not row.accumulated_depreciation_account or not frappe.db.exists(
            "Account", row.accumulated_depreciation_account
        ):
            row.accumulated_depreciation_account = self._get_or_create_account(
                company=company,
                account_name="Accumulated Depreciation",
                root_type="Asset",
                report_type="Balance Sheet",
                account_type="Accumulated Depreciation",
                preferred_parent_names=["Fixed Assets", "Application of Funds (Assets)", "Assets"],
            )

        if not row.depreciation_expense_account or not frappe.db.exists(
            "Account", row.depreciation_expense_account
        ):
            row.depreciation_expense_account = self._get_or_create_account(
                company=company,
                account_name="Depreciation",
                root_type="Expense",
                report_type="Profit and Loss",
                account_type="Depreciation",
                preferred_parent_names=["Indirect Expenses", "Expenses", "Direct Expenses"],
            )

        if not row.capital_work_in_progress_account or not frappe.db.exists(
            "Account", row.capital_work_in_progress_account
        ):
            row.capital_work_in_progress_account = self._get_or_create_account(
                company=company,
                account_name="CWIP Account",
                root_type="Asset",
                report_type="Balance Sheet",
                account_type="Capital Work in Progress",
                preferred_parent_names=["Fixed Assets", "Application of Funds (Assets)", "Assets"],
            )

    def _get_or_create_asset_category(self, category_name):
        """Return the category, leaving a new one unsaved until its required account row exists."""
        if frappe.db.exists("Asset Category", category_name):
            return frappe.get_doc("Asset Category", category_name)

        return frappe.get_doc(
            {
                "doctype": "Asset Category",
                "asset_category_name": category_name,
            }
        )

    def _get_or_create_account(
        self,
        *,
        company,
        account_name,
        root_type,
        report_type,
        account_type=None,
        preferred_parent_names=None,
    ):
        """Get an existing leaf Account or create it under a suitable parent group."""
        preferred_parent_names = preferred_parent_names or []

        company_abbr = frappe.db.get_value("Company", company, "abbr")
        expected_account = f"{account_name} - {company_abbr}"

        if frappe.db.exists("Account", expected_account):
            if not cint(frappe.db.get_value("Account", expected_account, "is_group")):
                return expected_account

            account_name = f"Rental {account_name}"
            expected_account = f"{account_name} - {company_abbr}"

            if frappe.db.exists("Account", expected_account):
                if not cint(frappe.db.get_value("Account", expected_account, "is_group")):
                    return expected_account

        existing = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "account_name": account_name,
                "root_type": root_type,
                "is_group": 0,
            },
            "name",
        )
        if existing:
            return existing

        parent_account = self._get_parent_account(
            company=company,
            root_type=root_type,
            preferred_parent_names=preferred_parent_names,
        )

        account = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": account_name,
                "company": company,
                "parent_account": parent_account,
                "is_group": 0,
                "root_type": root_type,
                "report_type": report_type,
                "account_type": account_type,
            }
        )
        account.insert(ignore_permissions=True)
        return account.name

    def _get_parent_account(self, *, company, root_type, preferred_parent_names=None):
        """Find a suitable group Account parent for creating a leaf account."""
        preferred_parent_names = preferred_parent_names or []
        company_abbr = frappe.db.get_value("Company", company, "abbr")

        for parent_name in preferred_parent_names:
            expected_parent = f"{parent_name} - {company_abbr}"

            if frappe.db.exists("Account", expected_parent):
                if cint(frappe.db.get_value("Account", expected_parent, "is_group")):
                    return expected_parent

            existing_parent = frappe.db.get_value(
                "Account",
                {
                    "company": company,
                    "account_name": parent_name,
                    "root_type": root_type,
                    "is_group": 1,
                },
                "name",
            )
            if existing_parent:
                return existing_parent

        root_parent = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "root_type": root_type,
                "is_group": 1,
                "parent_account": ["is", "not set"],
            },
            "name",
        )
        if root_parent:
            return root_parent

        fallback_parent = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "root_type": root_type,
                "is_group": 1,
            },
            "name",
        )
        if fallback_parent:
            return fallback_parent

        frappe.throw(
            _(
                "Could not find a parent Account for company {0} and root type {1}. "
                "Please create a group account first."
            ).format(company, root_type)
        )


@frappe.whitelist()
def retry_property_asset_setup(property_name):
    """Retry failed/pending Property Asset provisioning without blocking Desk."""
    property_doc = frappe.get_doc("Property", property_name)
    property_doc.check_permission("write")

    if property_doc.asset and frappe.db.exists("Asset", property_doc.asset):
        linked_asset = frappe.get_doc("Asset", property_doc.asset)
        if linked_asset.docstatus == 1:
            property_doc._mark_setup_completed()
            return {"status": "Completed", "asset": property_doc.asset}

    property_doc.db_set("setup_status", "Pending", update_modified=False)
    property_doc.db_set("setup_error", None, update_modified=False)
    property_doc.db_set("setup_completed_on", None, update_modified=False)
    property_doc._enqueue_asset_setup()
    return {"status": "Pending"}


def provision_property_asset(property_name):
    """Background entry point for Property Asset provisioning."""
    try:
        property_doc = frappe.get_doc("Property", property_name)
        property_doc._provision_asset()
    except Exception as exc:
        error_text = str(exc) or exc.__class__.__name__
        if frappe.db.exists("Property", property_name):
            frappe.db.set_value(
                "Property",
                property_name,
                {
                    "setup_status": "Failed",
                    "setup_error": error_text[:500],
                    "setup_completed_on": None,
                },
                update_modified=False,
            )
        frappe.log_error(
            frappe.get_traceback(),
            f"Property Asset Provisioning Failed: {property_name}",
        )
