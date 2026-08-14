# NetBBS v4.0.0

NetBBS v4.0.0 is the Phase 4 trust, quarantine, and identity-attestation
milestone. It establishes a stable deployment baseline before Phase 5
real-time Link chat work begins.

This release does **not** declare public-federation readiness. NetBBS Link
remains private and experimental while sustained dogfood and independently
administered trust/recovery exercises continue under issues #83 and #131.
Feedback from that ongoing deployment will become focused follow-up issues.

## Highlights

- Persisted, dimension-scoped local trust policy for nodes and users, with
  probation, establishment, quarantine, manual block, recovery holds, and
  restart reconstruction.
- Signed trust-signal, revocation, and vouch subscriptions with bounded,
  authenticated pulls; immutable carrier storage; issuer verification;
  replay/freshness defenses; quotas; and independently reproduced digest
  evidence.
- Trust enforcement across Link transport, synchronization, relay, content,
  and user projections. Unknown nodes begin in read-only probation;
  quarantine retains bounded containment paths; manual block denies service.
- Complete SysOp configuration and explanation workflows for domains,
  reporters, scopes, weights, anchors, sole-authority exceptions, overrides,
  recovery requirements, and audit history.
- Signed and revocable remote age/name attestations with explicit
  per-attribute subject opt-in, independent local authority grants,
  fail-closed resource gates, and reasoned local overrides.
- Adversarial validation covering Sybil-domain collapse, collusion
  thresholds, compromised-reporter removal, expiry/revocation, replay,
  oversized evidence, false evidence, subjective-report isolation, restart,
  preservation, containment, and resource bounds.
- Product improvements from ongoing dogfood: safer composition and
  review-before-send, clearer direct chat, truthful single-key confirmations,
  semantic color/capability reporting, and related usability fixes.

## Upgrade notes

- Back up the database, identity directory, and content storage before
  upgrading.
- Stop the running node cleanly, install the v4.0.0 package or tagged source,
  and start it normally. Shipped migrations are applied automatically.
- Do not downgrade a migrated live database to v3.x. Restore the pre-upgrade
  backup if rollback is required.
- Review Link trust policy after startup. Previously known peers do not gain
  trust authority merely by existing in the peer database; anchors,
  reporters, trust domains, and attestation authorities are separate local
  grants.
- Expect unknown remote nodes to be read-only probationary until local policy
  establishes them. This is an intentional compatibility and security
  boundary, and the reason for the major version bump.
- Follow `docs/NetBBS-link-dogfood-plan.md` for the ongoing private
  multi-node deployment and Phase 4 recovery exercise.

## Validation

The release candidate is accepted only after:

- the complete pytest suite passes;
- a wheel and source distribution build successfully;
- the wheel installs into a clean virtual environment;
- `python -m netbbs --version` reports v4.0.0 and the current schema;
- a realistic v3 database copy upgrades successfully and passes the startup
  integrity check.
