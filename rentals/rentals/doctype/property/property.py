# Copyright (c) 2025, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today, nowdate, flt, cint


class Property(Document):
    def validate(self):
        """Update Current Fair Value and Last Valuation Date from the last child row."""
        if self.accounting_model == "Fair Value Model" and self.valuation_history:
            last_entry = self.valuation_history[-1]
            self.current_fair_value = last_entry.valued_amount
            self.last_valuation_date = last_entry.valuation_date

    def after_insert(self):
        """Create and link an Asset record when a new Property is created."""
        company = frappe.db.get_value("Landlord", self.landlord, "company")

        if not company:
            frappe.throw(
                _("Landlord {0} does not have a linked Company.").format(self.landlord)
            )

        try:
            asset_category = self.ensure_company_in_asset_category(company)

            asset = frappe.get_doc(
                {
                    "doctype": "Asset",
                    "item_code": "Rental Property",
                    "asset_name": self.name,
                    "asset_category": asset_category,
                    "company": company,
                    "location": self.location,
                    "is_existing_asset": 1,
                    "purchase_date": today(),
                    "available_for_use_date": today(),
                    "gross_purchase_amount": flt(self.current_fair_value) or 1,
                }
            )

            if self.accounting_model == "Cost Model":
                asset.calculate_depreciation = 1
                asset.append(
                    "finance_books",
                    {
                        "depreciation_method": "Straight Line",
                        "frequency_of_depreciation": 1,
                        "total_number_of_depreciations": 1,
                        "depreciation_start_date": today(),
                    },
                )

            asset.insert(ignore_permissions=True)
            asset.submit()

            self.db_set("asset", asset.name)

            frappe.msgprint(
                _("✅ Property created successfully and linked to Asset <b>{0}</b>").format(
                    asset.name
                ),
                indicator="green",
                alert=True,
            )

        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Property.after_insert: Asset creation failed for {self.name}",
            )
            frappe.throw(_("Failed to create and link Asset. Please check logs."))

    def on_update(self):
        """Automates Journal Entry for fair value adjustments."""
        if self.accounting_model != "Fair Value Model" or len(self.valuation_history) < 2:
            return

        current_fair_value = flt(self.valuation_history[-1].valued_amount)
        previous_fair_value = flt(self.valuation_history[-2].valued_amount)
        change_in_value = current_fair_value - previous_fair_value

        if abs(change_in_value) < 0.01:
            return

        company = frappe.db.get_value("Landlord", self.landlord, "company")
        company_abbr = frappe.db.get_value("Company", company, "abbr")

        gain_loss_account = self._get_or_create_account(
            company=company,
            account_name="Gain/Loss on Asset Disposal",
            root_type="Expense",
            report_type="Profit and Loss",
            account_type=None,
            preferred_parent_names=[
                "Indirect Expenses",
                "Expenses",
                "Direct Expenses",
            ],
        )

        asset_account = self._get_or_create_account(
            company=company,
            account_name="Buildings",
            root_type="Asset",
            report_type="Balance Sheet",
            account_type="Fixed Asset",
            preferred_parent_names=[
                "Fixed Assets",
                "Application of Funds (Assets)",
                "Assets",
            ],
        )

        try:
            je = frappe.new_doc("Journal Entry")
            je.voucher_type = "Journal Entry"
            je.posting_date = nowdate()
            je.company = company
            je.remark = f"Fair value adjustment for property {self.name}"

            if change_in_value > 0:
                je.append(
                    "accounts",
                    {
                        "account": asset_account,
                        "debit_in_account_currency": abs(change_in_value),
                    },
                )
                je.append(
                    "accounts",
                    {
                        "account": gain_loss_account,
                        "credit_in_account_currency": abs(change_in_value),
                    },
                )
            else:
                je.append(
                    "accounts",
                    {
                        "account": asset_account,
                        "credit_in_account_currency": abs(change_in_value),
                    },
                )
                je.append(
                    "accounts",
                    {
                        "account": gain_loss_account,
                        "debit_in_account_currency": abs(change_in_value),
                    },
                )

            je.insert(ignore_permissions=True)
            je.submit()

            frappe.msgprint(
                _("Journal Entry <b>{0}</b> created for fair value adjustment.").format(
                    je.name
                ),
                indicator="green",
                alert=True,
            )

        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Property.on_update: Journal Entry creation failed for {self.name}",
            )

    def ensure_company_in_asset_category(self, company):
        """
        Ensure Asset Category 'Investment Property' has valid company accounts.

        The old code assumed these accounts already existed:
        - Buildings - COMPANY
        - Accumulated Depreciation - COMPANY
        - Depreciation - COMPANY
        - CWIP Account - COMPANY

        This version creates missing accounts safely before adding them
        to Asset Category.
        """
        category_name = "Investment Property"
        category = self._get_or_create_asset_category(category_name)

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
            preferred_parent_names=[
                "Fixed Assets",
                "Application of Funds (Assets)",
                "Assets",
            ],
        )

        accumulated_depreciation_account = self._get_or_create_account(
            company=company,
            account_name="Accumulated Depreciation",
            root_type="Asset",
            report_type="Balance Sheet",
            account_type="Accumulated Depreciation",
            preferred_parent_names=[
                "Fixed Assets",
                "Application of Funds (Assets)",
                "Assets",
            ],
        )

        depreciation_expense_account = self._get_or_create_account(
            company=company,
            account_name="Depreciation",
            root_type="Expense",
            report_type="Profit and Loss",
            account_type="Depreciation",
            preferred_parent_names=[
                "Indirect Expenses",
                "Expenses",
                "Direct Expenses",
            ],
        )

        capital_work_in_progress_account = self._get_or_create_account(
            company=company,
            account_name="CWIP Account",
            root_type="Asset",
            report_type="Balance Sheet",
            account_type="Capital Work in Progress",
            preferred_parent_names=[
                "Fixed Assets",
                "Application of Funds (Assets)",
                "Assets",
            ],
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

        category.save(ignore_permissions=True)

        frappe.msgprint(
            _("✅ Added valid accounts for company {0} in Asset Category '{1}'").format(
                company, category_name
            ),
            indicator="green",
            alert=True,
        )

        return category.name

    def _repair_asset_category_account_row(self, row, company):
        """Repair existing Asset Category account row if any linked account is missing."""
        if not row.fixed_asset_account or not frappe.db.exists("Account", row.fixed_asset_account):
            row.fixed_asset_account = self._get_or_create_account(
                company=company,
                account_name="Buildings",
                root_type="Asset",
                report_type="Balance Sheet",
                account_type="Fixed Asset",
                preferred_parent_names=[
                    "Fixed Assets",
                    "Application of Funds (Assets)",
                    "Assets",
                ],
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
                preferred_parent_names=[
                    "Fixed Assets",
                    "Application of Funds (Assets)",
                    "Assets",
                ],
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
                preferred_parent_names=[
                    "Indirect Expenses",
                    "Expenses",
                    "Direct Expenses",
                ],
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
                preferred_parent_names=[
                    "Fixed Assets",
                    "Application of Funds (Assets)",
                    "Assets",
                ],
            )

    def _get_or_create_asset_category(self, category_name):
        """Get or create Asset Category."""
        if frappe.db.exists("Asset Category", category_name):
            return frappe.get_doc("Asset Category", category_name)

        category = frappe.get_doc(
            {
                "doctype": "Asset Category",
                "asset_category_name": category_name,
            }
        )
        category.insert(ignore_permissions=True)
        return category

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
