# NetBBS v5.0.0

NetBBS v5.0.0 opens Phase 5 — real-time Link chat — while closing out Phase
4's remaining public-readiness gate (issue #131), and carries the largest
terminal-interface polish effort in the project's history: a redesigned
SysOp console, full display-width-aware Unicode/non-ASCII text handling, a
shared draft-based field editor with arrow-key cursor navigation, multi-
column menus with optional descriptions, and dozens of dogfood-reported
fixes across mail, search, moderation, directory, SSH, and SysOp reporting.

This release does **not** declare Phase 5 complete. What's shipped is Noise
XX transport authentication and the first real-time linked-channel chat
vertical (issue #148) — direct sessions and one linked channel, live.
Multiple simultaneous channel memberships with background/unread delivery
was investigated and deliberately not built this round (no observable
benefit over the existing durable unread-count model once the underlying
Link session's own always-on lifecycle was accounted for); it remains
Phase 5 scope for a future, narrowly-scoped pass. NetBBS Link remains
private and experimental, per the same posture v4.0.0 established.

## Highlights

- **Real-time Link chat (Phase 5, issue #148):** Noise XX-authenticated
  transport using node transport keys, live linked-channel chat over it,
  correct key rotation and shutdown teardown, and a fixed reference-
  counting bug in local live-subscription interest tracking that could
  silently cut off a second local watcher of the same linked channel.
- **Phase 4 public-readiness gate closed (issue #131):** the remaining
  adversarial-validation items are done; what's left toward full
  readiness is now purely human/operational (sustained multi-node
  dogfood duration, an independently-administered recovery exercise —
  issue #83), not further code-level validation.
- **Redesigned SysOp console and a full terminal-interface polish pass:**
  the operations console, discovery/profile, file library and transfers,
  live chat transitions, mail and composition, Community/board
  navigation, and the welcome/home experience were each reworked in
  turn for a more coherent, discoverable presentation.
- **Display-width-aware text handling throughout:** correct truncation,
  word-wrapping, and live cursor math for non-ASCII/wide characters
  across the line editor, prose editor, and reflow engine — plus a fix
  for umlaut/non-ASCII input corruption over Telnet.
- **A shared draft-based field editor**, replacing bespoke linear
  creation wizards for boards, channels, file areas, and Communities
  with one reusable "every field independently addressable, nothing
  written until explicit Save" screen — later extended with arrow-key/
  Space cursor navigation (Left/Right stepping cycling fields in place),
  and this release, with an immediate-persist mode reused to rebuild
  "Your profile" and "Name & details" — the two highest-traffic screens
  in the app — on the same driver, giving every user cursor navigation
  there too.
- **Multi-column menus with optional per-entry descriptions (issue
  #160):** rolled out across every hotkey menu in the app, with a
  per-user off/brief/detailed preference, plus real multi-column layout
  for single-section flat menus that previously stayed single-column
  regardless of terminal width.
- **New per-user preferences:** in-place screen redraw (clear-and-redraw
  instead of scrolling), and a Unicode breadcrumb style (arrow
  separator, ancestor/title coloring) with a one-time post-login
  garbled-display confirmation, defaulting on with a graceful plain-
  ASCII fallback.
- **Per-user, per-resource sort preferences**, wired into every board/
  file-area/channel picker's `[O]rder` command, with a review/clear
  screen so a forgotten override is never a silent mystery.
- **Identity/attestation polish:** trust-state and attestation-status
  badges, a colorized SysOp user-list picker, a bounded SysOp draft-
  pruning action, and a node-wide audit-log screen.
- **Dozens of dogfood-scouted fixes**, each round covering a real
  surface exercised end-to-end: mail/input, directory/vCard, full-text
  search, moderation (mute/ban/kick/blocklist), SSH transport/login,
  SysOp reporting and stats, and a real word-wrap crash plus several
  fullscreen-editor rough edges.

## Upgrade notes

- Back up the database, identity directory, and content storage before
  upgrading.
- Stop the running node cleanly, install the v5.0.0 package or tagged
  source, and start it normally. Shipped migrations are applied
  automatically.
- Do not downgrade a migrated live database to v4.x. Restore the
  pre-upgrade backup if rollback is required.
- If Link is enabled, expect the first real-time linked-channel chat
  session to trigger Noise XX key exchange on next connect — no manual
  step required, but worth watching node logs on the first upgrade of a
  multi-node deployment.
- Existing accounts see no behavior change from the new preferences
  (in-place redraw off by default; Unicode breadcrumb style on by
  default, with a one-time confirmation the first time each account
  logs in after upgrading).
- Follow `docs/NetBBS-link-dogfood-plan.md` for the ongoing private
  multi-node deployment; `docs/NetBBS-SysOp-Handbook.md` for the current
  console/menu reference.

## Validation

The release candidate is accepted only after:

- the complete pytest suite passes;
- a wheel and source distribution build successfully;
- the wheel installs into a clean virtual environment;
- `python -m netbbs --version` reports v5.0.0 and the current schema;
- a realistic v4 database copy upgrades successfully and passes the
  startup integrity check.
