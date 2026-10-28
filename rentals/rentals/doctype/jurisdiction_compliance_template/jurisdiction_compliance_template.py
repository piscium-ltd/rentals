
# Copyright (c) 2026, Piscium Solutions LTD and contributors
# For license information, please see license.txt

"""Date-driven jurisdiction compliance template lifecycle.

Features:
- Chronological revision ordering by legal effective dates.
- Automatic Scheduled, Active and Inactive statuses.
- Historical revision insertion.
- One Active template per applicability.
- Permanent supersession without automatic reactivation.
- Submission confirmation popups.
- Realtime succession and expiry popups for System Managers.
- Persistent Notification Logs for offline administrators.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime, today

DOCTYPE = "Jurisdiction Compliance Template"


# ============================================================
# APPLICABILITY AND DATA ACCESS
# ============================================================


def applicability_filters(doc):
    """Return the exact applicability identity."""

    filters = {
        "country": doc.country,
        "party_kind": doc.party_kind,
    }

    if doc.party_kind == "Individual":
        filters.update(
            has_business_name=doc.has_business_name,
            organization_type="",
        )

    elif doc.party_kind == "Organization":
        filters.update(
            has_business_name="",
            organization_type=doc.organization_type,
        )

    else:
        frappe.throw(
            _("Party Kind must be Individual or Organization.")
        )

    return filters


def _identity(row):
    """Identify templates belonging to the same applicability."""

    kind = row.get("party_kind")

    subtype = (
        row.get("has_business_name")
        if kind == "Individual"
        else row.get("organization_type")
    )

    return (
        row.get("country"),
        kind,
        subtype or "",
    )


def _lock_country(country):
    """Serialize submissions and reconciliation for a country."""

    rows = frappe.db.sql(
        """
        SELECT name
        FROM `tabCountry`
        WHERE name = %s
        FOR UPDATE
        """,
        (country,),
    )

    if not rows:
        frappe.throw(
            _("Country {0} does not exist.").format(country)
        )


def _submitted_for_country(country):
    """Fetch all submitted compliance templates for a country."""

    return frappe.get_all(
        DOCTYPE,
        filters={
            "country": country,
            "docstatus": 1,
        },
        fields=[
            "name",
            "country",
            "party_kind",
            "has_business_name",
            "organization_type",
            "template_status",
            "template_type",
            "predecessor",
            "successor",
            "superseded_on",
            "legal_effective_from",
            "legal_effective_to",
        ],
        order_by="creation asc, name asc",
    )


# ============================================================
# NOTIFICATION SYSTEM
# ============================================================


def _system_manager_users():
    """Return enabled System Managers with access to Desk."""

    users = frappe.get_all(
        "Has Role",
        filters={
            "role": "System Manager",
            "parenttype": "User",
        },
        pluck="parent",
    )

    enabled_users = []

    for user in sorted(set(users)):
        if user == "Guest":
            continue

        if frappe.db.get_value("User", user, "enabled"):
            enabled_users.append(user)

    # Administrator is not necessarily listed in Has Role.
    if (
        frappe.db.exists("User", "Administrator")
        and frappe.db.get_value(
            "User", "Administrator", "enabled"
        )
        and "Administrator" not in enabled_users
    ):
        enabled_users.append("Administrator")

    return enabled_users


def _send_realtime_popup(title, message, indicator="blue"):
    """Send a transactional popup to online System Managers.

    after_commit prevents delivery for rolled-back transactions.
    Offline users will not receive this transient popup.
    """

    for user in _system_manager_users():
        frappe.publish_realtime(
            event="msgprint",
            message={
                "title": title,
                "message": message,
                "indicator": indicator,
            },
            user=user,
            after_commit=True,
        )


def _create_notification_logs(
    title,
    message,
    document_name,
    event_key,
):
    """Persist notifications for System Managers.

    The event_key is incorporated into the subject so repeated
    reconciliation does not recreate the same event.

    Notification Log provides the notification bell and
    offline notification history.
    """

    for user in _system_manager_users():
        subject = "{0} [{1}]".format(title, event_key)

        existing = frappe.db.exists(
            "Notification Log",
            {
                "for_user": user,
                "document_type": DOCTYPE,
                "document_name": document_name,
                "subject": subject,
            },
        )

        if existing:
            continue

        notification = frappe.get_doc(
            {
                "doctype": "Notification Log",
                "type": "Alert",
                "for_user": user,
                "from_user": "Administrator",
                "document_type": DOCTYPE,
                "document_name": document_name,
                "subject": subject,
                "email_content": message,
                "read": 0,
            }
        )

        notification.insert(ignore_permissions=True)


def _notify_transition(
    event_type,
    template,
    predecessor=None,
    effective_date=None,
):
    """Notify System Managers about a real lifecycle transition."""

    template_name = template.name

    if event_type == "activated":
        title = _("Compliance Template Activated")

        if predecessor:
            message = _(
                "Compliance template {0} is now Active."
                "\n\nCountry: {1}"
                "\nParty Kind: {2}"
                "\nPredecessor: {3}"
                "\nEffective From: {4}"
                "\n\nThe predecessor has been superseded."
            ).format(
                template_name,
                template.country,
                template.party_kind,
                predecessor.name,
                template.legal_effective_from,
            )
        else:
            message = _(
                "Compliance template {0} is now Active."
                "\n\nCountry: {1}"
                "\nParty Kind: {2}"
                "\nEffective From: {3}"
            ).format(
                template_name,
                template.country,
                template.party_kind,
                template.legal_effective_from,
            )

        indicator = "green"

    elif event_type == "expired":
        title = _("Compliance Template Expired")

        message = _(
            "Compliance template {0} has expired."
            "\n\nCountry: {1}"
            "\nParty Kind: {2}"
            "\nEffective To: {3}"
            "\n\nNo Active replacement exists for this applicability."
        ).format(
            template_name,
            template.country,
            template.party_kind,
            template.legal_effective_to or "Not specified",
        )

        indicator = "orange"

    else:
        return

    event_key = "{0}:{1}:{2}".format(
        event_type,
        template_name,
        effective_date or today(),
    )

    _create_notification_logs(
        title=title,
        message=message,
        document_name=template_name,
        event_key=event_key,
    )

    _send_realtime_popup(
        title=title,
        message=message,
        indicator=indicator,
    )


# ============================================================
# REVISION CHAIN VALIDATION
# ============================================================


def _ordered_by_effectivity(rows):
    """Validate and order templates by their legal start dates.

    Existing nonchronological links are repaired during
    reconciliation.

    Invalid cross-applicability and dangling links are rejected.
    """

    if not rows:
        return []

    by_name = {
        row.name: row
        for row in rows
    }

    if len(by_name) != len(rows):
        frappe.throw(
            _("Duplicate compliance template records encountered.")
        )

    for row in rows:
        if not row.get("legal_effective_from"):
            frappe.throw(
                _(
                    "Submitted template {0} has no Effective From date."
                ).format(row.name)
            )

        start = getdate(row.legal_effective_from)

        end = (
            getdate(row.legal_effective_to)
            if row.get("legal_effective_to")
            else None
        )

        if end and end < start:
            frappe.throw(
                _("Template {0} expires before it starts.").format(
                    row.name
                )
            )

        for field in ("predecessor", "successor"):
            linked = row.get(field)

            if linked and linked not in by_name:
                frappe.throw(
                    _(
                        "Template {0} has a {1} outside its "
                        "applicability: {2}."
                    ).format(
                        row.name,
                        field,
                        linked,
                    )
                )

    ordered = sorted(
        rows,
        key=lambda row: (
            getdate(row.legal_effective_from),
            row.name,
        ),
    )

    for previous, current in zip(
        ordered,
        ordered[1:],
    ):
        if (
            getdate(previous.legal_effective_from)
            == getdate(current.legal_effective_from)
        ):
            frappe.throw(
                _(
                    "Templates {0} and {1} share Effective From {2}. "
                    "Specify distinct legal start dates."
                ).format(
                    previous.name,
                    current.name,
                    getdate(current.legal_effective_from),
                )
            )

    return ordered


# ============================================================
# LEGAL EFFECTIVITY AND STATUS
# ============================================================


def _status_at(row, index, ordered, as_of):
    """Determine authoritative legal status.

    A newer revision permanently supersedes older revisions
    when its Effective From date arrives.

    Expiration of the newest revision must not reactivate
    an older revision.
    """

    start = getdate(row.legal_effective_from)

    if start > as_of:
        return "Scheduled"

    # Later commenced revisions take precedence permanently.
    if any(
        getdate(revision.legal_effective_from) <= as_of
        for revision in ordered[index + 1:]
    ):
        return "Inactive"

    end = (
        getdate(row.legal_effective_to)
        if row.get("legal_effective_to")
        else None
    )

    if end and end < as_of:
        return "Inactive"

    return "Active"


def _reconcile_rows(
    rows,
    as_of,
    notify=False,
):
    """Repair revision links and reconcile lifecycle statuses.

    Notifications are emitted only for genuine status transitions
    observed by scheduled reconciliation.

    Initial data repair and direct submission reconciliation
    can suppress transition notifications.
    """

    ordered = _ordered_by_effectivity(rows)

    if not ordered:
        return ordered

    observed_at = None
    transitions = []

    for index, row in enumerate(ordered):
        previous = (
            ordered[index - 1]
            if index > 0
            else None
        )

        successor = (
            ordered[index + 1]
            if index + 1 < len(ordered)
            else None
        )

        expected_prev = (
            previous.name
            if previous
            else None
        )

        expected_next = (
            successor.name
            if successor
            else None
        )

        old_status = row.get("template_status")

        new_status = _status_at(
            row,
            index,
            ordered,
            as_of,
        )

        template_type = (
            "Initial"
            if index == 0
            else "Revision"
        )

        changes = {}

        if row.get("predecessor") != expected_prev:
            changes["predecessor"] = expected_prev

        if row.get("successor") != expected_next:
            changes["successor"] = expected_next

        if row.get("template_type") != template_type:
            changes["template_type"] = template_type

        if old_status != new_status:
            changes["template_status"] = new_status

        successor_commenced = (
            successor is not None
            and getdate(
                successor.legal_effective_from
            ) <= as_of
        )

        if (
            successor_commenced
            and not row.get("superseded_on")
        ):
            if observed_at is None:
                observed_at = now_datetime()

            changes["superseded_on"] = observed_at

        elif (
            not successor_commenced
            and row.get("superseded_on")
        ):
            changes["superseded_on"] = None

        if changes:
            frappe.db.set_value(
                DOCTYPE,
                row.name,
                changes,
                update_modified=False,
            )

        # Only a previously scheduled revision becoming active
        # represents a normal scheduled activation.
        if (
            notify
            and old_status == "Scheduled"
            and new_status == "Active"
            and getdate(row.legal_effective_from) == as_of
        ):
            transitions.append(
                {
                    "event": "activated",
                    "template": row,
                    "predecessor": previous,
                    "date": row.legal_effective_from,
                }
            )

        # Report an actual expiry without a commenced successor.
        if (
            notify
            and old_status == "Active"
            and new_status == "Inactive"
            and not successor_commenced
            and row.get("legal_effective_to")
            and getdate(row.legal_effective_to) < as_of
        ):
            transitions.append(
                {
                    "event": "expired",
                    "template": row,
                    "predecessor": previous,
                    "date": row.legal_effective_to,
                }
            )

    for transition in transitions:
        _notify_transition(
            event_type=transition["event"],
            template=transition["template"],
            predecessor=transition["predecessor"],
            effective_date=transition["date"],
        )

    return ordered


# ============================================================
# RECONCILIATION ENTRY POINTS
# ============================================================


def reconcile_country(
    country,
    as_of=None,
    lock=True,
    notify=False,
):
    """Reconcile all submitted templates within one country."""

    if lock:
        _lock_country(country)

    as_of_date = getdate(
        as_of or today()
    )

    groups = defaultdict(list)

    for row in _submitted_for_country(country):
        groups[_identity(row)].append(row)

    for rows in groups.values():
        _reconcile_rows(
            rows,
            as_of_date,
            notify=notify,
        )


def reconcile_all_template_statuses():
    """Scheduled reconciliation with automatic notifications.

    Register this function under scheduler_events["daily"].
    """

    countries = sorted(
        set(
            frappe.get_all(
                DOCTYPE,
                filters={
                    "docstatus": 1,
                },
                pluck="country",
            )
        )
    )

    for country in countries:
        reconcile_country(
            country,
            notify=True,
        )


# ============================================================
# DOCUMENT CONTROLLER
# ============================================================


class JurisdictionComplianceTemplate(Document):

    def validate(self):
        self._validate_applicability()
        self._validate_dates()

        if self.docstatus == 0:
            self.template_status = "Awaiting"
            self.template_type = None
            self.predecessor = None
            self.successor = None
            self.superseded_on = None

    def _validate_applicability(self):
        if not self.country:
            frappe.throw(
                _("Country is required.")
            )

        if self.party_kind == "Individual":
            if self.has_business_name not in (
                "Yes",
                "No",
            ):
                frappe.throw(
                    _(
                        "Has Business Name must be Yes or No "
                        "for an Individual."
                    )
                )

            self.organization_type = None

        elif self.party_kind == "Organization":
            field = frappe.get_meta(
                DOCTYPE
            ).get_field(
                "organization_type"
            )

            valid_types = (
                field.options or ""
            ).splitlines()

            if self.organization_type not in valid_types:
                frappe.throw(
                    _("Select a valid Organization Type.")
                )

            self.has_business_name = None

        else:
            frappe.throw(
                _(
                    "Party Kind must be Individual or Organization."
                )
            )

    def _validate_dates(self):
        if not self.legal_effective_from:
            frappe.throw(
                _("Effective From is required.")
            )

        if (
            self.legal_effective_to
            and getdate(self.legal_effective_to)
            < getdate(self.legal_effective_from)
        ):
            frappe.throw(
                _(
                    "Effective To cannot precede Effective From."
                )
            )

    def before_submit(self):
        self._validate_applicability()
        self._validate_dates()

        start = getdate(
            self.legal_effective_from
        )

        end = (
            getdate(self.legal_effective_to)
            if self.legal_effective_to
            else None
        )

        current_date = getdate(
            today()
        )

        # Provisional value. on_submit reconciles the full chain.
        self.template_status = (
            "Scheduled"
            if start > current_date
            else "Inactive"
            if end and end < current_date
            else "Active"
        )

    def on_submit(self):
        """Insert the submitted revision chronologically.

        Existing submitted revisions remain immutable with respect
        to legal dates, while system-managed chain links and
        lifecycle statuses are updated.
        """

        _lock_country(self.country)

        reconcile_country(
            self.country,
            lock=False,
            notify=False,
        )

        values = frappe.db.get_value(
            DOCTYPE,
            self.name,
            [
                "template_status",
                "template_type",
                "predecessor",
                "successor",
                "superseded_on",
            ],
            as_dict=True,
        )

        if not values:
            frappe.throw(
                _("Submitted template could not be reconciled.")
            )

        for key in (
            "template_status",
            "template_type",
            "predecessor",
            "successor",
            "superseded_on",
        ):
            self.set(
                key,
                values.get(key),
            )

        # Immediate feedback to the submitting user.
        message = _(
            "Compliance template {0} was submitted successfully."
            "\n\nCountry: {1}"
            "\nParty Kind: {2}"
            "\nTemplate Type: {3}"
            "\nPredecessor: {4}"
            "\nSuccessor: {5}"
            "\nEffective From: {6}"
            "\nEffective To: {7}"
            "\nCurrent Status: {8}"
        ).format(
            self.name,
            self.country,
            self.party_kind,
            self.template_type or "Initial",
            self.predecessor or "None",
            self.successor or "None",
            self.legal_effective_from,
            self.legal_effective_to or "Not specified",
            self.template_status,
        )

        frappe.msgprint(
            message,
            title=_(
                "Compliance Revision Registered"
            ),
            indicator="green",
        )

    def before_cancel(self):
        frappe.throw(
            _(
                "Submitted compliance templates cannot be cancelled. "
                "Submit a replacement revision instead."
            )
        )
