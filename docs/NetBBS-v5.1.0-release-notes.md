# NetBBS v5.1.0

A feature and polish release: a full terminal-interface style pass making
Unicode decoration actually consistent across the app instead of applied to
three call sites, a real fix for self-update release checks exhausting
GitHub's unauthenticated rate limit, an optional GitHub token for nodes that
want a much higher ceiling, a per-account signature auto-appended to mail
and board posts, and several smaller fixes found during ongoing dogfood/Link
deployment prep. No schema migration, no protocol change.

## Terminal style: a coherent pass, not three scattered call sites

A pre-5.0.0 styling effort left the app in an inconsistent state: the
`unicode_style` preference existed and defaulted on, but only three call
sites in the entire codebase actually used it, and even those disagreed —
one screen used a plain `/` breadcrumb separator, another used the intended
`›` arrow, and a third hand-built its own em dash. The two most-viewed
screens in the app — the main menu and the SysOp console — fell back to
plain ASCII regardless of the account's own preference.

This release finishes that rollout as one coherent pass, verified against a
live node at each step rather than by diff inspection alone:

- **Every `screen_title()` call site** (~75 of them: main menu, SysOp
  console and all its sub-screens, mail, board/chat/file-area pickers,
  search, sign-in/registration) now respects the account's actual
  `unicode_style` preference, replacing the old default-`False` fallback.
- **One canonical separator everywhere** — `›` for breadcrumbs, `─` for
  section rules — including the board/chat/file-area picker's compound
  titles, which previously hand-built a stray em dash instead of routing
  through the shared breadcrumb path.
- **Status indicators drop brackets for a colored dot** (`● ONLINE` instead
  of `[ONLINE]`) wherever they represent genuine state — online/disabled,
  accepted/not-accepted, up-to-date/update-available, live. Tags that
  aren't a health signal (a file size, an "edited" marker) are unchanged.
- **A double-line frame** (`╔═╗║╚╝`) is now NetBBS's one standard panel
  style — used on the welcome banner and the SysOp console's live-health
  panel, which is now a real boxed dashboard instead of a flat list.
- **Color separates fields on the same row** instead of one flat gray
  sentence: the main menu's `username › level N › mail status` line and
  the SysOp console's summary counts are each colored per field.

## Self-update: the actual fix for exhausted rate limits

Nodes were seeing `HTTP Error 403: rate limit exceeded` from GitHub's
release-check API, especially during rapid restarts (an ordinary dev-loop,
or a crash-restart loop). The release-check queries GitHub's unauthenticated
REST API, capped at 60 requests/hour **per source IP** — not per-repo or
per-install — and the scheduled check fires immediately on every node
startup, so repeated restarts independently exhaust that budget.

- **ETag conditional-request caching** was added, then verified directly
  against the real API: a `304 Not Modified` response still costs the same
  rate-limit unit as an ordinary request — GitHub does not exempt
  conditional requests from the primary limit. This is kept (it saves
  bandwidth/parsing and gives a clean "nothing changed" signal) but
  documented accurately as *not* a rate-limit fix.
- **A restart cooldown** (15 minutes, against the last recorded check
  attempt) is the actual fix for rapid-restart exhaustion: a restart within
  the cooldown window skips the immediate on-entry check entirely.
- **An optional GitHub personal access token** raises the ceiling itself —
  60/hour → 5000/hour. Set/replace/clear it from the Self-update admin
  screen (masked display, never re-shown in full once set); the prompt
  names the exact minimal scope needed ("Public Repositories, read-only").
  Stored as a plain, owner-only (`chmod 0600`) file next to the database,
  never in the plaintext `node_config` table — the same pattern already
  used for the node's own SSH/Link identity keys. A revoked/expired token
  gets its own specific error message instead of a generic "could not
  reach" one.

## New: per-account signatures

A caller can now write a short signature (Profile → `[g]` Signature, up to
4 lines / 500 bytes) that's automatically appended to mail messages and
board posts using the standard `-- ` delimiter line. Appended once per
compose — including across a saved-draft/resume cycle for board posts — not
re-added on every subsequent edit of the same draft; from that point on the
signature is ordinary text in the editable body, the same way a real mail
client's compose buffer works. Deliberately excludes live chat: a chat line
is conversational, not a message in the board-post/mail sense.

## Other fixes

- **Link now works behind a forward proxy.** `aiohttp.ClientSession()`
  defaulted to `trust_env=False`, so a node whose only outbound path is an
  HTTP(S) forward proxy (e.g. a corporate Squid array with no direct
  egress) could not dial any Link seed or peer at all. Both production
  `ClientSession` construction sites (the Link sync loop and linked-file
  fetches) now set `trust_env=True`, so the standard
  `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` environment variables work as
  expected.
- **SSH self-enrollment restored to the Profile screen.** A password-only,
  self-registered account had no way to add or replace its own SSH public
  key from its own Profile screen (it only worked from a SysOp's
  user-management screen). New `SSH public [k]ey` field.
- **Unicode decorative-style preference is now revisitable** via a new
  `[U]nicode style` field on Profile, instead of only being set once at a
  post-login confirmation prompt.
- **A misleading "asyncssh is not installed" message is fixed.** SSH
  startup wrapped its whole import in one broad `except ImportError`, so
  any import-time failure — not just asyncssh actually being absent — was
  misreported as "not installed," discarding the real cause. Observed on a
  node where `asyncssh` was correctly installed but the warning still
  appeared (the real cause was an OS-level shared-library path issue,
  unrelated to Python packaging). The presence check is now isolated to
  `import asyncssh` alone; any other import failure propagates with its
  real traceback.

## Upgrade notes

- No database migration in this release — upgrade is install-and-restart.
- Existing accounts see no behavior change beyond the new `[P]rofile`
  fields and the terminal style rollout (still opt-out via the `[U]nicode
  style` field, same as before).
- A node relying on a forward proxy for Link should set
  `HTTP_PROXY`/`HTTPS_PROXY` in its service environment before restarting
  on this version.
- A node whose release checks keep failing with a rate-limit error should
  set a GitHub token from the Self-update admin screen.

## Validation

- The complete pytest suite passes (3700+ tests).
- A wheel and source distribution build successfully.
- The wheel installs into a clean virtual environment.
- `python -m netbbs --version` reports v5.1.0 and the current schema.
- The terminal style rollout was verified against a live node over a real
  Telnet session (raw captures, not diff inspection) at each major step.
- The self-update rate-limit behavior (ETag conditional requests, the
  restart cooldown, and PAT authentication) was verified directly against
  the real GitHub API, not assumed from documentation.
- Every fix and new feature has regression tests confirmed to fail against
  the pre-fix/pre-feature code.
