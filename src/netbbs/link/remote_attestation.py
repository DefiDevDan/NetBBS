"""Signed remote identity attestations and local acceptance policy (issue #130).

Remote users remain :class:`TrustSubject` values.  This module never creates a
local account and never treats general trust-report authority as permission to
verify age or name.  Wire verification is completed before persistence; local
authority configuration, issuer trust state, expiry/revocation, and explicit
SysOp overrides determine the restart-safe acceptance projection.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Iterable

import nacl.exceptions
import nacl.signing

from netbbs.attestation import compute_age, get_attestation
from netbbs.auth.users import User
from netbbs.link.events import canonical_bytes
from netbbs.link.trust import (
    TrustDimension,
    TrustState,
    TrustSubject,
    get_effective_trust_state,
)
from netbbs.rendering import VERIFIED_COLOR, colored, sanitize_text
from netbbs.storage.database import Database
from netbbs.timeutil import utc_now_iso


REMOTE_ATTESTATION_OBJECT_TYPE = "remote_identity_attestation"
REMOTE_ATTESTATION_REVOCATION_OBJECT_TYPE = "remote_identity_attestation_revocation"
_ATTRIBUTES = frozenset({"age", "name"})
_MAX_NAME_BYTES = 128
_MAX_WIRE_BYTES = 16 * 1024
_MAX_LIFETIME = timedelta(days=365)
_FUTURE_TOLERANCE = timedelta(minutes=5)


@dataclass(frozen=True)
class AttestationAuthority:
    fingerprint: str
    attributes: tuple[str, ...]
    reason: str
    created_at: str


@dataclass(frozen=True)
class RemoteAttestation:
    content_id: str
    issuer_fingerprint: str
    subject: TrustSubject
    attribute: str
    attested_value: str
    issued_at: str
    expires_at: str
    revoked_at: str | None


@dataclass(frozen=True)
class RemoteAttestationState:
    subject: TrustSubject
    attribute: str
    accepted: bool
    reason_code: str
    attestation: RemoteAttestation | None
    explanation: dict[str, object]
    evaluated_at: str


@dataclass(frozen=True)
class RemoteAttestationOverride:
    override_id: int
    subject_id: str
    attribute: str
    accepted: bool
    reason: str
    created_at: str


@dataclass(frozen=True)
class RemoteAttestationAudit:
    audit_id: int
    subject_id: str | None
    object_kind: str
    object_id: str
    action: str
    details: dict[str, object]
    actor_user_id: int | None
    created_at: str


def _parse_time(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _now(now_iso: str | None) -> tuple[str, datetime]:
    value = now_iso or utc_now_iso()
    return value, _parse_time(value, "now")


def _validate_attribute(attribute: str) -> str:
    if attribute not in _ATTRIBUTES:
        raise ValueError(f"unknown attestation attribute: {attribute!r}")
    return attribute


def _validate_value(attribute: str, value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("attested value must not be blank")
    if attribute == "age":
        try:
            birthdate = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("age attestation must contain an ISO birthdate") from exc
        if birthdate > datetime.now(timezone.utc).date():
            raise ValueError("attested birthdate cannot be in the future")
    elif len(value.encode("utf-8")) > _MAX_NAME_BYTES:
        raise ValueError(f"attested name cannot exceed {_MAX_NAME_BYTES} bytes")
    return value


def _subject_payload(subject: TrustSubject) -> dict[str, str]:
    if subject.kind != "user" or subject.opaque_user_id is None:
        raise ValueError("remote attestations require a stable user subject")
    return {
        "kind": "user",
        "node_fingerprint": subject.node_fingerprint,
        "opaque_user_id": subject.opaque_user_id,
    }


def _subject_from_payload(payload: object) -> TrustSubject:
    if not isinstance(payload, dict) or set(payload) != {
        "kind", "node_fingerprint", "opaque_user_id"
    }:
        raise ValueError("remote attestation subject has an invalid shape")
    return TrustSubject(
        str(payload["kind"]), str(payload["node_fingerprint"]),
        str(payload["opaque_user_id"]),
    )


def _signed_wire(envelope: dict[str, object], signing_key: nacl.signing.SigningKey) -> dict[str, object]:
    signature = signing_key.sign(canonical_bytes(envelope)).signature
    return {"envelope": envelope, "signature": base64.b64encode(signature).decode("ascii")}


def build_remote_attestation(
    signing_key: nacl.signing.SigningKey,
    *,
    issuer_fingerprint: str,
    subject: TrustSubject,
    attribute: str,
    attested_value: str,
    subject_opt_in: bool,
    issued_at: str,
    expires_at: str,
) -> dict[str, object]:
    attribute = _validate_attribute(attribute)
    attested_value = _validate_value(attribute, attested_value)
    issued = _parse_time(issued_at, "issued_at")
    expires = _parse_time(expires_at, "expires_at")
    if expires <= issued or expires > issued + _MAX_LIFETIME:
        raise ValueError("remote attestation lifetime must be positive and at most 365 days")
    envelope: dict[str, object] = {
        "netbbs_protocol": 1,
        "object_type": REMOTE_ATTESTATION_OBJECT_TYPE,
        "payload": {
            "issuer_fingerprint": issuer_fingerprint,
            "subject": _subject_payload(subject),
            "attribute": attribute,
            "attested_value": attested_value,
            "subject_opt_in": bool(subject_opt_in),
            "issued_at": issued_at,
            "expires_at": expires_at,
        },
    }
    return _signed_wire(envelope, signing_key)


def build_link_visible_remote_attestation(
    db: Database,
    user: User,
    signing_key: nacl.signing.SigningKey,
    *,
    home_node_fingerprint: str,
    attribute: str,
    issued_at: str,
    expires_at: str,
) -> dict[str, object]:
    """Export one local attestation only after the subject opted in.

    The password-only Link identity is the same stable username-based opaque
    identifier used by current ``node_vouched_user`` events. Re-verification
    clears the local opt-in, so callers cannot accidentally export a replaced
    value under stale consent.
    """
    attestation = get_attestation(db, user, _validate_attribute(attribute))
    if attestation is None or not attestation.link_visible:
        raise ValueError("local attestation is missing or not explicitly Link-visible")
    return build_remote_attestation(
        signing_key,
        issuer_fingerprint=home_node_fingerprint,
        subject=TrustSubject.user(home_node_fingerprint, user.username),
        attribute=attribute,
        attested_value=attestation.attested_value,
        subject_opt_in=True,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def build_remote_attestation_revocation(
    signing_key: nacl.signing.SigningKey,
    *,
    issuer_fingerprint: str,
    revoked_content_id: str,
    issued_at: str,
) -> dict[str, object]:
    _parse_time(issued_at, "issued_at")
    envelope: dict[str, object] = {
        "netbbs_protocol": 1,
        "object_type": REMOTE_ATTESTATION_REVOCATION_OBJECT_TYPE,
        "payload": {
            "issuer_fingerprint": issuer_fingerprint,
            "revoked_content_id": revoked_content_id,
            "issued_at": issued_at,
        },
    }
    return _signed_wire(envelope, signing_key)


def _verify_wire(
    wire: dict[str, object], verify_key: nacl.signing.VerifyKey
) -> tuple[dict[str, object], dict[str, object], str, str]:
    if set(wire) != {"envelope", "signature"} or not isinstance(wire["envelope"], dict):
        raise ValueError("signed remote attestation has an invalid shape")
    envelope = wire["envelope"]
    encoded = canonical_bytes(envelope)
    if len(encoded) > _MAX_WIRE_BYTES:
        raise ValueError("signed remote attestation exceeds the wire-size limit")
    try:
        signature = base64.b64decode(str(wire["signature"]), validate=True)
        verify_key.verify(encoded, signature)
    except (ValueError, nacl.exceptions.BadSignatureError) as exc:
        raise ValueError("remote attestation signature is invalid") from exc
    if set(envelope) != {"netbbs_protocol", "object_type", "payload"}:
        raise ValueError("remote attestation envelope has unknown fields")
    if envelope["netbbs_protocol"] != 1 or not isinstance(envelope["payload"], dict):
        raise ValueError("unsupported remote attestation protocol or payload")
    payload = envelope["payload"]
    content_id = hashlib.sha256(encoded).hexdigest()
    return envelope, payload, str(envelope["object_type"]), content_id


def configure_attestation_authority(
    db: Database,
    fingerprint: str,
    *,
    attributes: Iterable[str],
    reason: str,
    actor_user_id: int | None = None,
    now_iso: str | None = None,
) -> None:
    normalized = tuple(sorted({_validate_attribute(value) for value in attributes}))
    if not fingerprint or not normalized or not reason.strip():
        raise ValueError("authority fingerprint, scope, and reason are required")
    now_value, _ = _now(now_iso)
    with db.connection:
        exists = db.connection.execute(
            "SELECT 1 FROM link_attestation_authorities WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        db.connection.execute(
            """INSERT INTO link_attestation_authorities
               (fingerprint, reason, actor_user_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(fingerprint) DO UPDATE SET reason = excluded.reason,
                 actor_user_id = excluded.actor_user_id, updated_at = excluded.updated_at""",
            (fingerprint, reason, actor_user_id, now_value, now_value),
        )
        db.connection.execute(
            "DELETE FROM link_attestation_authority_scopes WHERE authority_fingerprint = ?",
            (fingerprint,),
        )
        db.connection.executemany(
            """INSERT INTO link_attestation_authority_scopes
               (authority_fingerprint, attribute) VALUES (?, ?)""",
            [(fingerprint, attribute) for attribute in normalized],
        )
        _audit(
            db, None, "authority", fingerprint, "updated" if exists else "created",
            {"attributes": normalized, "reason": reason}, actor_user_id, now_value,
        )
        _recompute_all(db, now_value)


def remove_attestation_authority(
    db: Database,
    fingerprint: str,
    *,
    actor_user_id: int | None = None,
    now_iso: str | None = None,
) -> None:
    now_value, _ = _now(now_iso)
    with db.connection:
        row = db.connection.execute(
            "SELECT reason FROM link_attestation_authorities WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        if row is None:
            raise ValueError("attestation authority is missing or already removed")
        db.connection.execute(
            "DELETE FROM link_attestation_authorities WHERE fingerprint = ?", (fingerprint,)
        )
        _audit(db, None, "authority", fingerprint, "removed", {"reason": row["reason"]}, actor_user_id, now_value)
        _recompute_all(db, now_value)


def list_attestation_authorities(db: Database) -> list[AttestationAuthority]:
    rows = db.connection.execute(
        "SELECT fingerprint, reason, created_at FROM link_attestation_authorities ORDER BY fingerprint"
    ).fetchall()
    result: list[AttestationAuthority] = []
    for row in rows:
        scopes = db.connection.execute(
            """SELECT attribute FROM link_attestation_authority_scopes
               WHERE authority_fingerprint = ? ORDER BY attribute""",
            (row["fingerprint"],),
        ).fetchall()
        result.append(AttestationAuthority(row["fingerprint"], tuple(x["attribute"] for x in scopes), row["reason"], row["created_at"]))
    return result


def ingest_remote_attestation(
    db: Database,
    wire: dict[str, object],
    *,
    issuer_verify_key: nacl.signing.VerifyKey,
    now_iso: str | None = None,
) -> str:
    envelope, payload, object_type, content_id = _verify_wire(wire, issuer_verify_key)
    now_value, now = _now(now_iso)
    issuer = str(payload.get("issuer_fingerprint", ""))
    if not issuer:
        raise ValueError("remote attestation issuer is required")
    issued_at = str(payload.get("issued_at", ""))
    issued = _parse_time(issued_at, "issued_at")
    if issued > now + _FUTURE_TOLERANCE:
        raise ValueError("remote attestation is too far in the future")
    signature_b64 = str(wire["signature"])
    if object_type == REMOTE_ATTESTATION_REVOCATION_OBJECT_TYPE:
        expected = {"issuer_fingerprint", "revoked_content_id", "issued_at"}
        if set(payload) != expected:
            raise ValueError("remote attestation revocation has unknown fields")
        revoked_id = str(payload["revoked_content_id"])
        with db.connection:
            target = db.connection.execute(
                """SELECT subject_id, issuer_fingerprint FROM link_remote_attestations
                   WHERE content_id = ?""", (revoked_id,)
            ).fetchone()
            if target is None or target["issuer_fingerprint"] != issuer:
                raise ValueError("revocation target is unknown or belongs to another issuer")
            db.connection.execute(
                """INSERT OR IGNORE INTO link_remote_attestation_revocations
                   (content_id, issuer_fingerprint, revoked_content_id, envelope_json,
                    signature_b64, issued_at, received_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (content_id, issuer, revoked_id, json.dumps(envelope, sort_keys=True), signature_b64, issued_at, now_value),
            )
            db.connection.execute(
                """UPDATE link_remote_attestations SET revoked_by_content_id = ?, revoked_at = ?
                   WHERE content_id = ? AND revoked_at IS NULL""",
                (content_id, now_value, revoked_id),
            )
            _audit(db, target["subject_id"], "attestation", revoked_id, "revoked", {"revocation_content_id": content_id}, None, now_value)
            _recompute_subject_id(db, target["subject_id"], now_value)
        return content_id
    if object_type != REMOTE_ATTESTATION_OBJECT_TYPE:
        raise ValueError(f"unsupported remote attestation object type: {object_type!r}")
    expected = {
        "issuer_fingerprint", "subject", "attribute", "attested_value",
        "subject_opt_in", "issued_at", "expires_at",
    }
    if set(payload) != expected:
        raise ValueError("remote attestation payload has unknown fields")
    if payload["subject_opt_in"] is not True:
        raise ValueError("remote attestation lacks the subject's explicit Link opt-in")
    subject = _subject_from_payload(payload["subject"])
    attribute = _validate_attribute(str(payload["attribute"]))
    value = _validate_value(attribute, str(payload["attested_value"]))
    expires_at = str(payload["expires_at"])
    expires = _parse_time(expires_at, "expires_at")
    if expires <= issued or expires > issued + _MAX_LIFETIME:
        raise ValueError("remote attestation lifetime must be positive and at most 365 days")
    with db.connection:
        if not db.connection.execute(
            "SELECT 1 FROM link_trust_subjects WHERE subject_id = ?", (subject.subject_id,)
        ).fetchone():
            raise ValueError("remote attestation subject must already be a verified Link identity")
        db.connection.execute(
            """INSERT OR IGNORE INTO link_remote_attestations
               (content_id, issuer_fingerprint, subject_id, attribute, attested_value,
                subject_opt_in, issued_at, expires_at, envelope_json, signature_b64, received_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
            (content_id, issuer, subject.subject_id, attribute, value, issued_at, expires_at,
             json.dumps(envelope, sort_keys=True), signature_b64, now_value),
        )
        _audit(db, subject.subject_id, "attestation", content_id, "received", {"issuer": issuer, "attribute": attribute}, None, now_value)
        _recompute_subject_id(db, subject.subject_id, now_value)
    return content_id


def _issuer_is_locally_usable(db: Database, fingerprint: str) -> tuple[bool, str]:
    row = db.connection.execute(
        """SELECT subject_kind, node_fingerprint, opaque_user_id
           FROM link_trust_subjects WHERE subject_kind = 'node' AND node_fingerprint = ?""",
        (fingerprint,),
    ).fetchone()
    if row is None:
        return True, "explicit_attestation_authority"
    subject = TrustSubject(row["subject_kind"], row["node_fingerprint"], row["opaque_user_id"])
    state = get_effective_trust_state(db, subject, TrustDimension.IDENTITY_INTEGRITY)
    return state.state == TrustState.ESTABLISHED, f"authority_{state.state.value}"


def _subject_from_id(db: Database, subject_id: str) -> TrustSubject:
    row = db.connection.execute(
        """SELECT subject_kind, node_fingerprint, opaque_user_id
           FROM link_trust_subjects WHERE subject_id = ?""", (subject_id,)
    ).fetchone()
    if row is None:
        raise ValueError("unknown remote attestation subject")
    return TrustSubject(row["subject_kind"], row["node_fingerprint"], row["opaque_user_id"])


def _recompute_subject_id(db: Database, subject_id: str, now_value: str) -> None:
    subject = _subject_from_id(db, subject_id)
    for attribute in sorted(_ATTRIBUTES):
        _recompute(db, subject, attribute, now_value)


def _recompute_all(db: Database, now_value: str) -> None:
    rows = db.connection.execute("SELECT DISTINCT subject_id FROM link_remote_attestations").fetchall()
    for row in rows:
        _recompute_subject_id(db, row["subject_id"], now_value)


def _recompute(db: Database, subject: TrustSubject, attribute: str, now_value: str) -> None:
    override = db.connection.execute(
        """SELECT override_id, accepted, reason FROM link_remote_attestation_overrides
           WHERE subject_id = ? AND attribute = ? AND cleared_at IS NULL
           ORDER BY override_id DESC LIMIT 1""",
        (subject.subject_id, attribute),
    ).fetchone()
    candidates = db.connection.execute(
        """SELECT a.* FROM link_remote_attestations AS a
           WHERE a.subject_id = ? AND a.attribute = ? AND a.revoked_at IS NULL
             AND a.expires_at > ? ORDER BY a.issued_at DESC, a.content_id DESC""",
        (subject.subject_id, attribute, now_value),
    ).fetchall()
    usable = []
    rejected_issuers: list[dict[str, str]] = []
    for candidate in candidates:
        configured = db.connection.execute(
            """SELECT 1 FROM link_attestation_authority_scopes
               WHERE authority_fingerprint = ? AND attribute = ?""",
            (candidate["issuer_fingerprint"], attribute),
        ).fetchone()
        if not configured:
            rejected_issuers.append(
                {"issuer": candidate["issuer_fingerprint"], "reason": "authority_not_configured_for_attribute"}
            )
            continue
        allowed, reason = _issuer_is_locally_usable(db, candidate["issuer_fingerprint"])
        if allowed:
            usable.append(candidate)
        else:
            rejected_issuers.append({"issuer": candidate["issuer_fingerprint"], "reason": reason})
    selected = usable[0] if usable else None
    if override is not None:
        accepted = bool(override["accepted"])
        reason_code = "sysop_accept" if accepted else "sysop_reject"
        if accepted and candidates:
            selected = candidates[0]
        elif accepted:
            accepted = False
            reason_code = "sysop_accept_without_current_attestation"
        explanation: dict[str, object] = {
            "override_id": int(override["override_id"]), "override_reason": override["reason"],
            "rejected_issuers": rejected_issuers,
        }
    elif selected is not None:
        accepted = True
        reason_code = "trusted_attestation_authority"
        explanation = {"issuer": selected["issuer_fingerprint"], "expires_at": selected["expires_at"]}
    else:
        accepted = False
        reason_code = "no_current_trusted_attestation"
        explanation = {"rejected_issuers": rejected_issuers}
    content_id = selected["content_id"] if selected is not None else None
    db.connection.execute(
        """INSERT INTO link_remote_attestation_effective
           (subject_id, attribute, accepted, reason_code, attestation_content_id,
            explanation_json, evaluated_at) VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(subject_id, attribute) DO UPDATE SET
             accepted = excluded.accepted, reason_code = excluded.reason_code,
             attestation_content_id = excluded.attestation_content_id,
             explanation_json = excluded.explanation_json, evaluated_at = excluded.evaluated_at""",
        (subject.subject_id, attribute, int(accepted), reason_code, content_id,
         json.dumps(explanation, sort_keys=True, separators=(",", ":")), now_value),
    )


def get_remote_attestation_state(
    db: Database,
    subject: TrustSubject,
    attribute: str,
    *,
    now_iso: str | None = None,
) -> RemoteAttestationState:
    attribute = _validate_attribute(attribute)
    now_value, _ = _now(now_iso)
    with db.connection:
        _recompute(db, subject, attribute, now_value)
    row = db.connection.execute(
        """SELECT * FROM link_remote_attestation_effective
           WHERE subject_id = ? AND attribute = ?""",
        (subject.subject_id, attribute),
    ).fetchone()
    attestation = None
    if row["attestation_content_id"] is not None:
        source = db.connection.execute(
            "SELECT * FROM link_remote_attestations WHERE content_id = ?",
            (row["attestation_content_id"],),
        ).fetchone()
        attestation = RemoteAttestation(
            source["content_id"], source["issuer_fingerprint"], subject,
            source["attribute"], source["attested_value"], source["issued_at"],
            source["expires_at"], source["revoked_at"],
        )
    return RemoteAttestationState(
        subject, attribute, bool(row["accepted"]), row["reason_code"], attestation,
        json.loads(row["explanation_json"]), row["evaluated_at"],
    )


def set_remote_attestation_override(
    db: Database,
    subject: TrustSubject,
    attribute: str,
    *,
    accepted: bool,
    reason: str,
    actor_user_id: int | None = None,
    now_iso: str | None = None,
) -> int:
    attribute = _validate_attribute(attribute)
    if not reason.strip():
        raise ValueError("remote attestation override reason is required")
    now_value, _ = _now(now_iso)
    with db.connection:
        db.connection.execute(
            """UPDATE link_remote_attestation_overrides SET cleared_at = ?
               WHERE subject_id = ? AND attribute = ? AND cleared_at IS NULL""",
            (now_value, subject.subject_id, attribute),
        )
        cursor = db.connection.execute(
            """INSERT INTO link_remote_attestation_overrides
               (subject_id, attribute, accepted, reason, actor_user_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (subject.subject_id, attribute, int(accepted), reason, actor_user_id, now_value),
        )
        _audit(db, subject.subject_id, "override", str(cursor.lastrowid), "created", {"attribute": attribute, "accepted": accepted, "reason": reason}, actor_user_id, now_value)
        _recompute(db, subject, attribute, now_value)
        return int(cursor.lastrowid)


def clear_remote_attestation_override(
    db: Database,
    override_id: int,
    *,
    actor_user_id: int | None = None,
    now_iso: str | None = None,
) -> None:
    now_value, _ = _now(now_iso)
    with db.connection:
        row = db.connection.execute(
            """SELECT subject_id, attribute FROM link_remote_attestation_overrides
               WHERE override_id = ? AND cleared_at IS NULL""", (override_id,)
        ).fetchone()
        if row is None:
            raise ValueError("remote attestation override is missing or already cleared")
        db.connection.execute(
            "UPDATE link_remote_attestation_overrides SET cleared_at = ? WHERE override_id = ?",
            (now_value, override_id),
        )
        _audit(db, row["subject_id"], "override", str(override_id), "cleared", {"attribute": row["attribute"]}, actor_user_id, now_value)
        _recompute(db, _subject_from_id(db, row["subject_id"]), row["attribute"], now_value)


def list_remote_attestation_overrides(
    db: Database, subject: TrustSubject
) -> list[RemoteAttestationOverride]:
    rows = db.connection.execute(
        """SELECT override_id, subject_id, attribute, accepted, reason, created_at
           FROM link_remote_attestation_overrides
           WHERE subject_id = ? AND cleared_at IS NULL ORDER BY override_id DESC""",
        (subject.subject_id,),
    ).fetchall()
    return [
        RemoteAttestationOverride(
            int(row["override_id"]), row["subject_id"], row["attribute"],
            bool(row["accepted"]), row["reason"], row["created_at"],
        )
        for row in rows
    ]


def list_remote_attestation_audit(
    db: Database, subject: TrustSubject | None = None, *, limit: int = 100
) -> list[RemoteAttestationAudit]:
    if limit < 1:
        raise ValueError("audit limit must be positive")
    if subject is None:
        rows = db.connection.execute(
            """SELECT * FROM link_remote_attestation_audit
               ORDER BY audit_id DESC LIMIT ?""", (limit,)
        ).fetchall()
    else:
        rows = db.connection.execute(
            """SELECT * FROM link_remote_attestation_audit
               WHERE subject_id = ? ORDER BY audit_id DESC LIMIT ?""",
            (subject.subject_id, limit),
        ).fetchall()
    return [
        RemoteAttestationAudit(
            int(row["audit_id"]), row["subject_id"], row["object_kind"],
            row["object_id"], row["action"], json.loads(row["details_json"]),
            row["actor_user_id"], row["created_at"],
        )
        for row in rows
    ]


def remote_meets_age(
    db: Database, subject: TrustSubject, min_age: int | None, *, now_iso: str | None = None
) -> bool:
    if not min_age:
        return True
    state = get_remote_attestation_state(db, subject, "age", now_iso=now_iso)
    if not state.accepted or state.attestation is None:
        return False
    today = _parse_time(now_iso, "now").date() if now_iso is not None else None
    return compute_age(date.fromisoformat(state.attestation.attested_value), today=today) >= min_age


def remote_meets_name_requirement(
    db: Database, subject: TrustSubject, requirement: str | None, *, now_iso: str | None = None
) -> bool:
    if requirement is None:
        return True
    return get_remote_attestation_state(db, subject, "name", now_iso=now_iso).accepted


def format_remote_name_for_resource(
    db: Database,
    subject: TrustSubject,
    display_label: str,
    *,
    name_requirement: str | None,
    now_iso: str | None = None,
) -> str:
    """Render an accepted remote real name only inside a requiring resource."""
    primary = sanitize_text(display_label)
    if name_requirement != "verified_and_displayed":
        return primary
    state = get_remote_attestation_state(db, subject, "name", now_iso=now_iso)
    if not state.accepted or state.attestation is None:
        return primary
    unit = colored(
        f"(={sanitize_text(state.attestation.attested_value)}=)",
        fg_color=VERIFIED_COLOR,
    )
    return f"{primary} {unit}"


def _audit(
    db: Database,
    subject_id: str | None,
    object_kind: str,
    object_id: str,
    action: str,
    details: dict[str, object],
    actor_user_id: int | None,
    now_value: str,
) -> None:
    db.connection.execute(
        """INSERT INTO link_remote_attestation_audit
           (subject_id, object_kind, object_id, action, details_json, actor_user_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (subject_id, object_kind, object_id, action,
         json.dumps(details, sort_keys=True, separators=(",", ":")), actor_user_id, now_value),
    )
