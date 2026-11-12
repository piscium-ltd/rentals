
# Copyright (c) 2026, Piscium Solutions LTD and contributors
# For license information, please see license.txt

import hashlib
import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, get_url, now_datetime

from rentals.utils.id_generator import (
    generate_luhn_number,
    calculate_luhn_check_digit,
)


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

DOCTYPE = "Party Legal and Compliance Identity"

PARTY_CODE_PREFIX = "PLCI"
PARTY_CODE_PATTERN = re.compile(r"^PLCI[0-9]{7}$")

EMAIL_TEMPLATE = "Party Legal and Compliance Email Verification"

APPLICANT_ROLES = (
    "Jurisdiction Compliance Template",
    "Jurisdiction Profile Release Applicant",
    "Identity Record",
)

VERIFICATION_EXPIRY_HOURS = 24
RESEND_COOLDOWN_SECONDS = 60

VERIFY_METHOD = (
    "rentals.rentals.doctype."
    "party_legal_and_compliance_identity."
    "party_legal_and_compliance_identity.verify_email"
)

INVALID_VERIFICATION_LINK = (
    "Invalid or expired verification link."
)


# ---------------------------------------------------------
# Verification token helpers
# ---------------------------------------------------------

def generate_verification_token():
    """Generate a cryptographically secure verification token."""
    return secrets.token_urlsafe(32)


def _token_hash(token):
    """Hash a verification token before database storage."""
    return (
        "sha256:"
        + hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()
    )


def _prepare_email_verification(doc):
    """
    Reset verification state and generate a fresh token.

    The plaintext token exists only in memory.
    Only its SHA-256 digest is stored in the database.
    """

    doc.email_verified = 0
    doc.lifecycle_status = "Pending Verification"

    doc.flags.plain_email_verification_token = None

    doc.email_verification_token = None
    doc.email_verification_expires_at = None
    doc.last_email_verification_sent_at = None

    if not doc.email:
        return

    raw_token = generate_verification_token()
    now = now_datetime()

    doc.email_verification_token = _token_hash(raw_token)

    doc.email_verification_expires_at = (
        now + timedelta(hours=VERIFICATION_EXPIRY_HOURS)
    )

    doc.last_email_verification_sent_at = now

    doc.flags.plain_email_verification_token = raw_token


def _verification_url(doc, raw_token):
    """Generate the public email verification URL."""

    query = urlencode({
        "name": doc.name,
        "token": raw_token,
    })

    return get_url(
        f"/api/method/{VERIFY_METHOD}?{query}"
    )


def _is_valid_verification_token(stored_token, supplied_token):
    """
    Verify a token using constant-time comparison.

    Supports hashed tokens and legacy plaintext tokens.
    """

    if not stored_token or not supplied_token:
        return False

    if not isinstance(supplied_token, str):
        return False

    stored_token = str(stored_token)

    if stored_token.startswith("sha256:"):
        expected = _token_hash(supplied_token)
    else:
        # Legacy plaintext-token compatibility.
        expected = supplied_token

    return secrets.compare_digest(
        stored_token,
        expected,
    )


def redirect_verification_success():
    """
    Redirect only after successful verification
    and committed User provisioning.
    """

    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = "/verify-email-success"
    frappe.local.response["http_status_code"] = 302

    return None


# ---------------------------------------------------------
# Send verification email
# ---------------------------------------------------------

def send_verification_email(doc):
    """Send an email containing the verification link."""

    raw_token = getattr(
        doc.flags,
        "plain_email_verification_token",
        None,
    )

    if (
        not doc.email
        or doc.email_verified
        or not raw_token
    ):
        return

    template = frappe.get_doc(
        "Email Template",
        EMAIL_TEMPLATE,
    )

    context = {
        "doc": doc,
        "verification_url": _verification_url(
            doc,
            raw_token,
        ),
        "expiry_hours": VERIFICATION_EXPIRY_HOURS,
    }

    subject = frappe.render_template(
        template.subject,
        context,
    )

    message = frappe.render_template(
        template.response_html or template.response,
        context,
    )

    frappe.sendmail(
        recipients=[doc.email],
        subject=subject,
        message=message,
        reference_doctype=doc.doctype,
        reference_name=doc.name,
        delayed=False,
        now=True,
    )

    # The raw token must not remain attached to the document.
    doc.flags.plain_email_verification_token = None


# ---------------------------------------------------------
# Party Code generation
# ---------------------------------------------------------

def _is_valid_party_code(code):
    """Validate PLCI-prefixed, seven-digit Luhn codes."""

    if (
        not isinstance(code, str)
        or not PARTY_CODE_PATTERN.fullmatch(code)
    ):
        return False

    digits = [
        int(value)
        for value in code[len(PARTY_CODE_PREFIX):]
    ]

    return (
        digits[-1]
        == calculate_luhn_check_digit(digits[:-1])
    )


def _new_party_code():
    """Generate an unused Party Code."""

    for _ in range(100):
        code = (
            f"{PARTY_CODE_PREFIX}"
            f"{generate_luhn_number(7)}"
        )

        if not frappe.db.exists(
            DOCTYPE,
            {"party_code": code},
        ):
            return code

    frappe.throw(
        "Unable to generate a unique Party Code "
        "after 100 attempts."
    )


@frappe.whitelist()
def get_new_party_code():
    """Preview a Party Code without inserting a document."""

    if not frappe.has_permission(
        DOCTYPE,
        "create",
    ):
        frappe.throw(
            "Not permitted to create "
            "Party Legal and Compliance Identity.",
            frappe.PermissionError,
        )

    return _new_party_code()


# ---------------------------------------------------------
# PLCI Document Controller
# ---------------------------------------------------------

class PartyLegalandComplianceIdentity(Document):

    def before_insert(self):
        """Generate Party Code and verification token."""

        if (
            not _is_valid_party_code(self.party_code)
            or frappe.db.exists(
                DOCTYPE,
                {"party_code": self.party_code},
            )
        ):
            self.party_code = _new_party_code()

        _prepare_email_verification(self)

    def before_validate(self):
        """Reset verification when the email changes."""

        if (
            not self.is_new()
            and self.has_value_changed("email")
        ):
            previous = self.get_doc_before_save()

            # A verified, linked identity must not be
            # silently transferred to another email.
            if (
                previous
                and previous.email_verified
                and previous.get("portal_user")
            ):
                frappe.throw(
                    "This identity is linked to a User account. "
                    "Contact an administrator to change its email."
                )

            _prepare_email_verification(self)

    def validate(self):
        """Protect Party Code and server-managed fields."""

        if self.is_new():
            return

        if self.has_value_changed("party_code"):
            frappe.throw(
                "Party Code cannot be changed after creation."
            )

        previous = self.get_doc_before_save()

        if not previous:
            return

        if getattr(
            self.flags,
            "allow_email_verification_update",
            False,
        ):
            return

        protected_fields = (
            "email_verified",
            "lifecycle_status",
            "email_verification_token",
            "email_verification_expires_at",
            "last_email_verification_sent_at",
        )

        if self.meta.has_field("portal_user"):
            protected_fields += ("portal_user",)

        email_changed = self.has_value_changed("email")

        for field in protected_fields:
            if self.get(field) == previous.get(field):
                continue

            # Email changes legitimately reset
            # verification state in before_validate().
            #
            # A portal_user relationship cannot
            # be changed through this exception.
            if (
                field != "portal_user"
                and email_changed
            ):
                continue

            frappe.throw(
                f"{field} cannot be changed manually."
            )

    def after_insert(self):
        """Send the initial verification email."""
        send_verification_email(self)

    def on_update(self):
        """Send a fresh email after an email-address change."""

        if (
            self.get_doc_before_save()
            and self.has_value_changed("email")
        ):
            send_verification_email(self)


# ---------------------------------------------------------
# Create or reuse User and assign all applicant roles
# ---------------------------------------------------------

def create_user_from_verified_plci(doc):
    """
    Create or reuse a Frappe User after email verification.

    Assign:
    - Jurisdiction Compliance Template
    - Jurisdiction Profile Release Applicant
    - Identity Record

    Preserve any existing roles and account settings.

    Called within the email verification transaction.
    """

    if not doc.email or not doc.email_verified:
        frappe.throw(
            "Email verification is required "
            "before creating a User account."
        )

    # All roles must exist before provisioning.
    for role in APPLICANT_ROLES:
        if not frappe.db.exists("Role", role):
            frappe.throw(
                f"Required role '{role}' does not exist."
            )

    email = doc.email.strip().lower()

    # ---------------------------------------------
    # Check for an existing User
    # ---------------------------------------------

    existing_user = frappe.db.get_value(
        "User",
        {"email": email},
        "name",
    )

    if existing_user:
        user = frappe.get_doc(
            "User",
            existing_user,
        )

        existing_roles = {
            row.role
            for row in user.get("roles", [])
        }

        missing_roles = [
            role
            for role in APPLICANT_ROLES
            if role not in existing_roles
        ]

        if missing_roles:
            # add_roles() saves the User.
            user.add_roles(*missing_roles)

        return user.name

    # ---------------------------------------------
    # Create a new User
    # ---------------------------------------------

    user = frappe.get_doc({
        "doctype": "User",
        "email": email,
        "first_name": doc.party_code,
        "enabled": 1,
        "user_type": "System User",
        "send_welcome_email": 1,
        "roles": [
            {"role": role}
            for role in APPLICANT_ROLES
        ],
    })

    user.insert(ignore_permissions=True)

    return user.name


# ---------------------------------------------------------
# Resend verification email
# ---------------------------------------------------------

@frappe.whitelist(methods=["POST"])
def resend_verification_email(name):
    """
    Resend verification with a 60-second cooldown.

    Lock the PLCI row to prevent concurrent resends.
    """

    if not frappe.has_permission(
        DOCTYPE,
        "write",
        doc=name,
    ):
        frappe.throw(
            "Not permitted to update this identity.",
            frappe.PermissionError,
        )

    matched = frappe.db.sql(
        f"""
        SELECT name
        FROM `tab{DOCTYPE}`
        WHERE name = %s
        FOR UPDATE
        """,
        (name,),
        as_dict=True,
    )

    if not matched:
        frappe.throw(
            "Identity record not found."
        )

    doc = frappe.get_doc(DOCTYPE, name)

    doc.check_permission("write")

    if not doc.email:
        frappe.throw(
            "Add an email address before "
            "requesting verification."
        )

    if doc.email_verified:
        frappe.throw(
            "This email address is already verified."
        )

    last_sent = doc.last_email_verification_sent_at

    if last_sent:
        elapsed = (
            now_datetime() - get_datetime(last_sent)
        ).total_seconds()

        if elapsed < RESEND_COOLDOWN_SECONDS:
            remaining = max(
                1,
                int(RESEND_COOLDOWN_SECONDS - elapsed) + 1,
            )

            frappe.throw(
                f"Please wait {remaining} seconds "
                "before resending verification."
            )

    _prepare_email_verification(doc)

    doc.flags.allow_email_verification_update = True

    # Frappe commits the successful POST request.
    doc.save()

    send_verification_email(doc)

    return {
        "message": "Verification email sent.",
        "cooldown_seconds": RESEND_COOLDOWN_SECONDS,
    }


# ---------------------------------------------------------
# Verify email and provision Frappe User
# ---------------------------------------------------------

@frappe.whitelist(
    allow_guest=True,
    methods=["GET"],
)
def verify_email(name, token):
    """
    Verify a PLCI email and provision its User account.

    Operations:
    1. Lock the PLCI row.
    2. Reject used, invalid, or expired tokens.
    3. Validate any existing User relationship.
    4. Mark email as verified.
    5. Create or reuse the Frappe User.
    6. Assign all three applicant roles.
    7. Link the User to the PLCI.
    8. Commit the database transaction.
    9. Redirect to the success page.

    Any exception before commit rolls back the database
    changes made in the transaction.

    GET is retained for existing email-link compatibility.
    """

    if (
        not isinstance(name, str)
        or not isinstance(token, str)
        or not name
        or not token
    ):
        frappe.throw(INVALID_VERIFICATION_LINK)

    # Account ownership must be persisted.
    # Never provision an unlinked applicant User.
    if not frappe.get_meta(DOCTYPE).has_field("portal_user"):
        frappe.throw(
            "The portal_user field is required "
            "for PLCI account provisioning."
        )

    try:
        # ---------------------------------------------
        # Lock PLCI row
        # ---------------------------------------------

        matched = frappe.db.sql(
            f"""
            SELECT name
            FROM `tab{DOCTYPE}`
            WHERE name = %s
            FOR UPDATE
            """,
            (name,),
            as_dict=True,
        )

        if not matched:
            frappe.throw(INVALID_VERIFICATION_LINK)

        doc = frappe.get_doc(DOCTYPE, name)

        # ---------------------------------------------
        # Reject already-verified PLCI
        # ---------------------------------------------

        # A consumed token must never return success.
        # Do not reveal whether the PLCI exists or
        # whether the email was previously verified.
        if doc.email_verified:
            frappe.throw(INVALID_VERIFICATION_LINK)

        if not doc.email:
            frappe.throw(INVALID_VERIFICATION_LINK)

        stored_token = doc.email_verification_token

        if not stored_token:
            frappe.throw(INVALID_VERIFICATION_LINK)

        # ---------------------------------------------
        # Validate verification token
        # ---------------------------------------------

        if not _is_valid_verification_token(
            stored_token,
            token,
        ):
            frappe.throw(INVALID_VERIFICATION_LINK)

        # ---------------------------------------------
        # Validate token expiry
        # ---------------------------------------------

        expires_at = doc.email_verification_expires_at

        if (
            not expires_at
            or now_datetime() > get_datetime(expires_at)
        ):
            frappe.throw(
                "Verification link expired. "
                "Please request another verification email."
            )

        # ---------------------------------------------
        # Validate existing User relationship
        # ---------------------------------------------

        existing_link = doc.get("portal_user")

        if existing_link:
            linked_email = frappe.db.get_value(
                "User",
                existing_link,
                "email",
            )

            if (
                not linked_email
                or linked_email.strip().lower()
                != doc.email.strip().lower()
            ):
                frappe.throw(
                    "This identity is already linked "
                    "to another User account. "
                    "Contact an administrator."
                )

        # ---------------------------------------------
        # Mark PLCI email as verified
        # ---------------------------------------------

        doc.email_verified = 1
        doc.lifecycle_status = "Valid"

        # Permanently consume this verification token.
        doc.email_verification_token = None
        doc.email_verification_expires_at = None

        doc.flags.allow_email_verification_update = True

        doc.save(ignore_permissions=True)

        # ---------------------------------------------
        # Create or reuse User
        # ---------------------------------------------

        user_name = create_user_from_verified_plci(doc)

        # ---------------------------------------------
        # Ensure PLCI cannot switch User
        # ---------------------------------------------

        if (
            existing_link
            and existing_link != user_name
        ):
            frappe.throw(
                "This identity is linked "
                "to a different User account."
            )

        # ---------------------------------------------
        # Link User to PLCI
        # ---------------------------------------------

        if doc.portal_user != user_name:
            doc.portal_user = user_name

            doc.save(ignore_permissions=True)

        # ---------------------------------------------
        # Commit all database changes together
        # ---------------------------------------------

        # Required because this endpoint uses GET.
        # No successful redirect is returned before
        # User provisioning is committed.
        frappe.db.commit()

    except Exception:
        # Roll back the current database transaction.
        #
        # This protects against partial verification
        # if account provisioning or linking fails.
        frappe.db.rollback()
        raise

    # ---------------------------------------------
    # Redirect after successful commit
    # ---------------------------------------------

    return redirect_verification_success()
