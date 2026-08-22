# NetBBS v5.2.0

A dogfood-driven feature release: cursor-navigation now reaches four more
screens, new accounts get in-place redraw on by default, the login banner
is genuinely colorful at every color depth (including, for the first time,
over SSH), and an audit closed real on-demand-help gaps across the entire
app. No schema migration, no protocol change.

## Cursor-navigation, everywhere it was still missing

Issue #160's arrow-key/Space navigation now reaches the last four screens
that didn't have it:

- **The SysOp user-detail screen** (Level/Status/Identity-verify/Public
  key/Blocked) and **the post/mail review screen** (To/Subject/Body) are
  now arrow-navigable — both keep their own bespoke dispatch loop rather
  than the shared draft-editor driver, since Delete needs to end the whole
  screen mid-field and the review screen is a stateless function with no
  draft of its own.
- **Timestamp settings** no longer forces format and timezone to be
  visited together — each is now an independently addressable field, so a
  SysOp who only wants to fix one doesn't have to re-enter the other.
- **The create-user wizard** drops its old forced username → password? →
  key? → level sequence for a real draft-editor screen: every field
  addressable in any order, with `[C]reate` only validating once you're
  ready.

## In-place redraw now defaults on for new accounts

Three dogfood testers on modern, ANSI-capable clients never discovered
in-place redraw existed, so never turned it on. New accounts — whether
self-registered or created by a SysOp — now start with it already on,
with a one-time notice pointing at Your profile if you'd rather scroll.
Existing accounts are completely untouched.

## The login banner, actually colorful — and now shown over SSH too

- **A new "rainbow" gradient** (the existing presets were all single-hue
  fades) colors the "N E T B B S" wordmark at both color depths, plus a
  solid gold accent on "NetBBS Link" — no more flat cyan.
- **SSH connections now see the real welcome banner before authenticating**,
  not a bare hand-typed "NetBBS" line. The design doc had claimed SSH
  already showed this at truecolor depth; it never actually did — SSH's
  pre-auth banner is now the same content Telnet/web show, always at the
  safe 256-color depth (SSH's own protocol phase has no way to know the
  client's real color capability that early).
- **The "Color depth" profile override now actually works.** It always
  claimed to "force a terminal color depth," but the one screen that
  renders a truecolor/256 choice — the SysOp welcome-banner Preview —
  silently ignored it. Fixed; forcing truecolor or 256 in Your profile
  now changes what the Preview screen shows, regardless of what your
  client actually negotiated.

## A full help-text audit, closed

An audit ranked every screen by how much a newcomer would actually get
stuck on it, then closed the gaps:

- **"Your profile" and "Name & details"** — the two highest-traffic
  screens in the app — now have real Ctrl-H help on all 19 fields.
  Cursor-nav had already reached them; Ctrl-H was a discoverable dead end
  until now.
- **Every Board/Area/Channel/Community create-edit screen, plus
  create-user and timestamp-settings** — the remaining 42 SysOp-facing
  fields now have help text too.
- **Every board/channel/file-area/user list screen** had no help
  mechanism at all — just a terse one-line description when menu
  descriptions are on. Ctrl-H now explains Next/Prev/2-digit-select/
  Search/Goto #/Order/Back/Ctrl-L/Ctrl-R, each shown only when that
  particular screen actually offers it.
- **The SysOp user-detail and post/mail review screens** (this release's
  own new cursor-nav screens) got Ctrl-H wired in too, not left as a
  known gap.

Already solid and correctly left alone: chat's `/help`, the registration
flow's inline hints, and the main menu's existing brief descriptions.

## Upgrade notes

- No database migration in this release — upgrade is install-and-restart.
- New accounts (self-registered or SysOp-created) now default to
  in-place redraw **on**; every existing account's own setting is
  unchanged.
- No other default behavior changes for existing accounts — everything
  else in this release is either purely additive (cursor-nav, help text)
  or a rendering-accuracy fix (the SSH banner, the Color-depth override).

## Validation

- The complete pytest suite passes (3760+ tests), including new
  regression coverage for every cursor-nav screen's Ctrl-H, the picker's
  new help overlay, the SSH banner content over a real SSH client
  connection, and the Color-depth override actually flipping the
  Preview screen's rendering.
- A wheel and source distribution build successfully.
- `python -m netbbs --version` reports v5.2.0 and the current (unchanged)
  schema version.
- Every fix has a regression test confirmed to fail against the pre-fix
  code.
