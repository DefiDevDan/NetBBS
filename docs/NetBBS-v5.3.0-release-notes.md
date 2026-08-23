# NetBBS v5.3.0

A feature and dogfood-polish release: SysOps can now brand a node's masthead
and its accent/header/clock colors end-to-end, two of Phase 5's three
remaining real-time chat gaps are closed, and the item picker gained
arrow-key navigation plus several real usability fixes. No schema migration,
no protocol change.

## Node branding: masthead and colors (issues #161, #162)

Parts two and three of the skinning initiative the welcome banner started:

- **A SysOp-configurable main-menu masthead.** An optional `.ans` banner
  shown above the still-fully-live main menu (mail count, conditional
  entries, node status, and every per-user preference render exactly as
  before, underneath it) — same enable/disable/preview/edit/size-cap
  mechanism the welcome banner already used. Backed up and restored along
  with the other branding artifacts.
- **Node-wide accent, header, and clock color overrides — fully wired,
  with a real admin screen.** `netbbs.net.node_theme` resolves a SysOp-set
  RGB override for each of the three "branding" colors (downgraded to the
  nearest 256-color index for a session without truecolor support), in
  place of the bare constant, at every real render call site across the
  entire app — every screen, every shared rendering primitive
  (`screen_title`, pickers, editors, review screens), close to 100 call
  sites in total. **Settings → `[C]olors`** is the new screen that actually
  sets or clears each override: it previews the candidate color against
  real sample text (a board name, a section header, a clock) at both
  truecolor and 256-color depth before asking to commit.
- **Deliberately narrow, on purpose.** Every semantic/status color (error,
  warning, success, privilege, alert, verified-identity) stays fixed on
  every node, never overridable — a caller who has used several NetBBS
  nodes can keep trusting that red always means failure and green always
  means verified/success, regardless of any node's own branding. Full
  palette theming was considered and rejected on exactly that basis, not
  merely deferred as too large.
- **22 bundled ANSI/Unicode banner and masthead presets** (welcome banners
  and mastheads, both truecolor and 256-color) ship in the gallery so a
  SysOp can pick a look with zero filesystem access to the node.

With nothing configured, every existing node's output is byte-for-byte
unchanged.

## Two of Phase 5's three remaining real-time chat gaps closed (issue #164)

- **Node-wide presence.** `[W]ho's online` now mixes in every known remote
  node's live roster alongside local sessions — visible by default, the
  same "who's online" stance the local screen already took. Since
  Link-wide live private chat doesn't exist yet (tracked separately as
  issue #168), selecting a remote entry says so plainly rather than
  offering an action that doesn't work.
- **Trust-filtered scrollback.** Linked-channel scrollback is now filtered
  through the same trust policy board posts already enforce — suppressing
  only a blocked/quarantined *author's* messages, never a merely
  quarantined relay's. This closes a real, pre-existing inconsistency with
  boards, not a new policy question.

## Arrow-key navigation in the item picker (issue #171)

Up/Down now move a highlight and Enter selects it, purely additive
alongside the existing 2-digit numbered selection. Nothing is highlighted
until the first arrow press, so the screen looks identical to today until
then. Doesn't wrap at a page's top/bottom — the picker keeps its own
`[N]ext`/`[P]rev` boundary convention instead.

## Smaller dogfood-driven fixes

- **The Enter-selected default in a y/N confirmation prompt is now
  highlighted**, plus the surrounding `[`/`]` brackets are colored — both
  make it clearer at a glance that a keystroke is expected and which
  answer Enter would pick. Deliberately not a red/green good/bad mapping,
  since these prompts guard both safe and destructive actions.
- **The picker hides `[N]ext`/`[P]rev` when there's no page to go to**,
  instead of always showing both and silently bell-rejecting a press at
  either end.
- **Item names in a picker listing now align regardless of stable-id
  digit count** — a page mixing `(#1)` and `(#23)` no longer leaves
  single-digit rows one column further left than the rest.
- **The welcome-banner and masthead gallery's Preview no longer flashes
  away instantly** with in-place redraw on, and its status/description/menu
  blocks are now visually separated instead of running together.
- **Declining a gallery preset now loops back into the same gallery**
  instead of exiting to the parent menu, so a SysOp can browse several
  samples in one visit.

## Upgrade notes

- No database migration in this release — upgrade is install-and-restart.
- No default behavior changes for existing accounts or nodes — every
  branding override is opt-in and unset by default; every other change is
  either purely additive or a targeted usability fix.

## Validation

- The complete pytest suite passes (3862 passed, 5 skipped).
- A wheel and source distribution build successfully.
- `python -m netbbs --version` reports v5.3.0 and the current (unchanged)
  schema version.
- Every fix has a regression test confirmed to fail against the pre-fix
  code.
