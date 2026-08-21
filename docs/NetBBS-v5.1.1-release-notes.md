# NetBBS v5.1.1

A dogfood-driven polish release: the node's own name now appears in the
breadcrumb instead of a hardcoded "NetBBS", the breadcrumb collapses
sensibly when it doesn't fit, and a batch of consistency/UX bugs found
during a real dogfood session are fixed — several screens that never
picked up the unicode_style/redraw_in_place terminal-style rollout at all,
a fake breadcrumb that mimicked the real one's color split without being
one, and a redundant confirmation prompt. No schema migration, no protocol
change.

## Breadcrumb: the node's own name, and a real collapse option

- **The breadcrumb root now reflects the node's actual name** instead of
  the hardcoded literal `"NetBBS"` — a new node-wide "display name"
  setting (Settings → node identity, default unchanged: `"NetBBS"`),
  resolved once per session.
- **The breadcrumb collapses to just the current location** when the full
  path doesn't fit the terminal, replacing the old ellipsis truncation,
  which cut off the *current* location — the one thing a breadcrumb
  actually needs to show — while keeping the least useful part
  (`"NetBBS / Sys…"`). A new per-account **Location style** field on
  Profile forces this short form always, for anyone who just doesn't want
  the ancestor noise even with room to spare.

## Theming consistency: the parts the previous pass missed

The v5.1.0 style rollout covered `screen_title()`'s ~75 call sites, but
missed a related surface: `pick_item()`'s own `unicode_style`/
`redraw_in_place`/`collapsed` parameters, which many call sites never
passed at all. Found via a live dogfood session, not diff inspection:

- **Directory, the category list/delete screen, and "Uncategorized"
  browsing** rendered plain ASCII with no in-place redraw regardless of
  the account's actual preferences — the picker call was simply missing
  all three parameters. Audited and fixed across every `pick_item()` call
  site in the app (~50 total, spanning the SysOp console, mail, the ANSI
  welcome-banner editor, and the ordinary board/channel/file-area
  browsing screens).
- **A fake breadcrumb, fixed for real.** Three screens (browsing
  boards/channels/areas inside a category or Community) built their own
  breadcrumb by hand, folding the category/Community name into the title
  text with a `›` separator — visually identical to a real breadcrumb's
  muted-ancestor/colored-current-location split, without actually being
  one; the whole string rendered in one flat color. `pick_item()` now
  takes a real `breadcrumb=` parameter, and all three screens use it.

## Other fixes

- **"Last sessions" no longer gets wiped by its own return.** It used to
  print the listing and return immediately, with the caller unconditionally
  redrawing the main menu right after — under in-place redraw, that
  cleared the terminal before there was any chance to read it. It now
  shows a real heading and waits for a keystroke before returning, the
  same "Press any key to continue…" convention already used elsewhere.
- **The main menu heading's stray trailing colon is gone** (`"Main menu"`,
  not `"Main menu:"`).
- **A `menu_key()` typo that spelled "reqquirement"** is fixed across all
  four screens that had it (board/area/channel/community name-requirement
  fields) — the hotkey and the prefix text overlapped by one letter.
- **`screen_title()`'s divider now spans whichever of the location line or
  the subtitle is actually wider**, not just the location line — a
  subtitle routinely carries more detail than the breadcrumb above it, and
  a rule sized only to the shorter line stopped short of a heading block
  that was still going.
- **The profile screen gets a blank line after the bio** (before the
  transport-report line that follows it), and its field labels are now
  colored instead of rendering in the terminal's default foreground.
- **Esc cancels cursor-navigation's highlight** on the draft-editor screens
  (board/area/channel/Community create+edit, and Profile) instead of doing
  nothing — it drops the `>` highlight and returns to plain hotkey input on
  the same screen, without leaving it; `[B]ack`/Ctrl-C remain the way to
  actually leave.
- **The "Assign a category?"/"Assign a Community?" confirmation prompts are
  gone.** They were a holdover from before these were directly addressable
  fields on the cursor-nav field list — pressing the field's own hotkey is
  already the "yes, I want this" gesture, and the picker's own `[B]ack` is
  the actual decline affordance. The prompt used to fire even with zero
  categories/Communities to offer, only to immediately show "none exist
  yet." after an already-pointless "yes."

## Upgrade notes

- No database migration in this release — upgrade is install-and-restart.
- A node that has never touched the node display name keeps showing
  `"NetBBS"` in the breadcrumb, byte-for-byte unchanged, until a SysOp sets
  one explicitly.
- Existing accounts see no behavior change beyond the fixed screens above
  and the new `[L]ocation style` Profile field (off/auto by default, same
  as before).

## Validation

- The complete pytest suite passes (3740+ tests), including new regression
  coverage for the confirm-prompt removal, the Esc/cursor-nav cancel
  behavior, and the divider-width fix.
- A wheel and source distribution build successfully.
- `python -m netbbs --version` reports v5.1.1 and the current schema.
- Every fix has a regression test confirmed to fail against the pre-fix
  code.
