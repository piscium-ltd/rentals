
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


# ---------------------------------------------------------
# Verification token helpers
# ---------------------------------------------------------

def generate_verification_token():
    """Generate a cryptographically secure token."""
    return secrets.token_urlsafe(32)


def _token_hash(token):
    """Hash the token before database storage."""
    return (
        "sha256:"
        + hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()
    )


def _prepare_email_verification(doc):
    """Generate a fresh email verification token."""

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

    doc.email_verification_token = _token_hash(
        raw_token
    )

    doc.email_verification_expires_at = (
        now + timedelta(
            hours=VERIFICATION_EXPIRY_HOURS
        )
    )

    doc.last_email_verification_sent_at = now

    # Keep plaintext token only in memory.
    doc.flags.plain_email_verification_token = raw_token


def _verification_url(doc, raw_token):
    """Generate a public verification link."""

    query = urlencode({
        "name": doc.name,
        "token": raw_token,
    })

    return get_url(
        f"/api/method/{VERIFY_METHOD}?{query}"
    )


def redirect_verification_success(already_verified=False):
    """Redirect to the verification success page."""

    location = "/verify-email-success"

    if already_verified:
        location += "?already_verified=1"

    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = location
    frappe.local.response["http_status_code"] = 302

    return None


# ---------------------------------------------------------
# Send verification email
# ---------------------------------------------------------

def send_verification_email(doc):
    """Send the verification email immediately."""

    raw_token = getattr(
        doc.flags,
        "plain_email_verification_token",
        None
    )

    if (
        not doc.email
        or doc.email_verified
        or not raw_token
    ):
        return

    template = frappe.get_doc(
        "Email Template",
        EMAIL_TEMPLATE
    )

    context = {
        "doc": doc,
        "verification_url": _verification_url(
            doc,
            raw_token
        ),
        "expiry_hours": VERIFICATION_EXPIRY_HOURS,
    }

    subject = frappe.render_template(
        template.subject,
        context
    )

    message = frappe.render_template(
        template.response_html or template.response,
        context
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

    doc.flags.plain_email_verification_token = None


# ---------------------------------------------------------
# Party Code generation
# ---------------------------------------------------------

def _is_valid_party_code(code):
    """Validate PLCI-prefixed seven-digit Luhn codes."""

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
            {"party_code": code}
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
        "create"
    ):
        frappe.throw(
            "Not permitted to create "
            "Party Legal and Compliance Identity",
            frappe.PermissionError
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
                {"party_code": self.party_code}
            )
        ):
            self.party_code = _new_party_code()

        _prepare_email_verification(self)

    def before_validate(self):
        """Reset verification when email changes."""

        if (
            not self.is_new()
            and self.has_value_changed("email")
        ):
            # A verified identity already linked to a
            # Frappe account must not silently transfer
            # that relationship to another email.
            previous = self.get_doc_before_save()

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

        if getattr(
            self.flags,
            "allow_email_verification_update",
            False
        ):
            return

        previous = self.get_doc_before_save()

        if not previous:
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

        for field in protected_fields:

            if self.get(field) == previous.get(field):
                continue

            if (
                field != "portal_user"
                and self.has_value_changed("email")
            ):
                continue

            frappe.throw(
                f"{field} cannot be changed manually."
            )

    def after_insert(self):
        """Send initial verification email."""

        send_verification_email(self)

    def on_update(self):
        """Send another verification email when email changes."""

        if (
            self.get_doc_before_save()
            and self.has_value_changed("email")
        ):
            send_verification_email(self)


# ---------------------------------------------------------
# Create User and assign applicant role
# ---------------------------------------------------------

def create_user_from_verified_plci(doc):
    """
    Create or reuse a Frappe User after email verification.

    Assign all three applicant roles.
    Preserve existing User roles and account settings.
    """

    if not doc.email or not doc.email_verified:
        frappe.throw(
            "Email verification is required "
            "before creating a User account."
        )

    # Validate that all required roles exist.
    for role in APPLICANT_ROLES:
        if not frappe.db.exists("Role", role):
            frappe.throw(
                f"Required role '{role}' does not exist."
            )

    email = doc.email.strip().lower()

    existing_user = frappe.db.get_value(
        "User",
        {"email": email},
        "name",
    )

    # ---------------------------------------------
    # Existing User
    # ---------------------------------------------

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
    # New User
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
    """Resend verification with a 60-second cooldown."""

    if not frappe.has_permission(
        DOCTYPE,
        "write",
        doc=name
    ):
        frappe.throw(
            "Not permitted to update this identity.",
            frappe.PermissionError
        )

    matched = frappe.db.sql(
        f"""
        SELECT name
        FROM `tab{DOCTYPE}`
        WHERE name = %s
        FOR UPDATE
        """,
        (name,),
        as_dict=True
    )

    if not matched:
        frappe.throw(
            "Identity record not found."
        )

    doc = frappe.get_doc(
        DOCTYPE,
        name
    )

    doc.check_permission("write")

    if not doc.email:
        frappe.throw(
            "Add an email address before requesting verification."
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
                int(
                    RESEND_COOLDOWN_SECONDS - elapsed
                ) + 1
            )

            frappe.throw(
                f"Please wait {remaining} seconds "
                "before resending verification."
            )

    _prepare_email_verification(doc)

    doc.flags.allow_email_verification_update = True

    doc.save()

    send_verification_email(doc)

    return {
        "message": "Verification email sent.",
        "cooldown_seconds": RESEND_COOLDOWN_SECONDS,
    }


# ---------------------------------------------------------
# Verify email and create User account
# ---------------------------------------------------------

@frappe.whitelist(
    allow_guest=True,
    methods=["GET"]
)
def verify_email(name, token):
    """
    Verify email and provision a Frappe User.

    After verification:
    - Mark PLCI as Valid.
    - Invalidate verification token.
    - Create or reuse User.
    - Assign applicant role.
    - Link User to PLCI if field exists.
    """

    matched = frappe.db.sql(
        f"""
        SELECT name
        FROM `tab{DOCTYPE}`
        WHERE name = %s
        FOR UPDATE
        """,
        (name,),
        as_dict=True
    )

    if not matched:
        frappe.throw(
            "Invalid verification link."
        )

    doc = frappe.get_doc(
        DOCTYPE,
        name
    )

    # Already verified:
    # Do not consume the token again or repeat provisioning.
    if doc.email_verified:
        return redirect_verification_success(
            already_verified=True
        )

    stored_token = doc.email_verification_token

    if (
        not doc.email
        or not stored_token
        or not token
    ):
        frappe.throw(
            "This verification link is no longer valid."
        )

    # Validate hashed token.
    if str(stored_token).startswith("sha256:"):
        expected = _token_hash(str(token))
    else:
        # Support legacy plaintext tokens.
        expected = str(token)

    if not secrets.compare_digest(
        str(stored_token),
        expected
    ):
        frappe.throw(
            "Invalid email verification link."
        )

    # Check expiry.
    if (
        not doc.email_verification_expires_at
        or now_datetime() > get_datetime(
            doc.email_verification_expires_at
        )
    ):
        frappe.throw(
            "Verification link expired. "
            "Please request another verification email."
        )

    # ---------------------------------------------
    # Mark PLCI as verified
    # ---------------------------------------------

    doc.email_verified = 1
    doc.lifecycle_status = "Valid"

    doc.email_verification_token = None
    doc.email_verification_expires_at = None

    doc.flags.allow_email_verification_update = True

    doc.save(ignore_permissions=True)

    # ---------------------------------------------
    # Create User and assign applicant role
    # ---------------------------------------------

    user_name = create_user_from_verified_plci(doc)

    # ---------------------------------------------
    # Link User to PLCI
    # ---------------------------------------------

    if doc.meta.has_field("portal_user"):

        existing_link = doc.portal_user

        if (
            existing_link
            and existing_link != user_name
        ):
            frappe.throw(
                "This identity is linked to another User. "
                "Contact an administrator."
            )

        doc.portal_user = user_name

        doc.save(ignore_permissions=True)

    # Commit verification and User creation together.
    frappe.db.commit()

    return redirect_verification_success()
