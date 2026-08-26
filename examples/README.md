# Sample assets

## Service supervisor examples (issue #82)

- `netbbs.service` — a systemd unit for Linux (design doc §2.1 Tier 2).
- `netbbs.rc` — an rc.d script for NetBSD (design doc §2.1 Tier 1),
  following standard `rc.subr(8)` conventions but **not yet run-tested
  on real NetBSD hardware** — see the file's own header comment.

Both assume a config file at a fixed path (`/etc/netbbs/netbbs.toml` on
Linux, `/usr/pkg/etc/netbbs/netbbs.toml` on NetBSD) and run NetBBS in
the foreground, letting the service supervisor manage backgrounding and
restart — NetBBS never daemonizes itself (design doc §13.8). See
`docs/NetBBS-operator-guide.md` for the full install-through-running
path these fit into.

## Welcome banners and main-menu mastheads

NetBBS ships a set of sample welcome banners (issue #161) and main-menu
mastheads (issue #161), illustrating different aesthetic directions,
color depths, and modern Unicode features, all designed for standard
80-column terminal displays.

These no longer live in this directory as loose files to `cp` into
place — `examples/` is not part of the installed package
(`pyproject.toml`'s `[tool.setuptools.packages.find]` is scoped to
`src/` only), so a node running from a release wheel would have had no
sample files on its filesystem to copy from in the first place. Instead
(issue #169), every sample is bundled as real installed package data
under `src/netbbs/net/banner_presets/`, and browsable entirely from
within the running BBS:

`[S]ysOp` → `[S]ystem` → `[W]elcome banner` or `[M]asthead` → `[G]allery`
lists every bundled preset by name and description, `[P]review`-style,
before you apply one. Selecting a preset shows it decoded exactly as a
connecting user would see it; confirming writes it to the same
well-known path `[E]nable`/`[I] edit` already operate on and turns it on
immediately. No filesystem access to the node is needed, and it works
identically from a wheel install or a source checkout.

To tweak an applied preset afterward, use `Ed[i]t` on the same screen —
the fullscreen WYSIWYG ANSI art editor opens against whatever is
currently in place.

See `src/netbbs/net/banner_presets/__init__.py` for the full preset
list and descriptions.

## Sample door game (issue #172)

- `doors/retro_trivia.py` — a real, playable multiple-choice trivia
  door: eight random questions per round, single-keystroke (A/B/C/D)
  answers, a running score, and a colored final rank. Zero external
  dependencies (stdlib only), and runnable completely standalone
  outside NetBBS too (`python3 examples/doors/retro_trivia.py` from a
  real terminal) for trying it before registering it.

Unlike the banners/mastheads above, a door genuinely *is* meant to be an
external program a SysOp points at — it deliberately stays a loose file
here rather than becoming installed package data; nothing about the
door sandbox model expects NetBBS to ship or bundle doors itself.

To register it: `[S]ysOp` → `[M]anage boards/areas/channels` (Content)
→ `[D]oors` → `[C]reate`, then set **Executable path** to your `python3`
interpreter and **Arguments** to the full path to `retro_trivia.py` on
your node's own filesystem (e.g. wherever you cloned/installed NetBBS
from). Callers can then find and play it from `[G]ames` in the normal
board/file-area/chat browsing menu.

See `src/netbbs/doors/runtime.py` for the sandbox model this runs
under — same-OS-user subprocess isolation with enforced resource/time
limits, not a container, and door output is trusted and shown exactly
as generated (see that module's own docstring for the full reasoning).
