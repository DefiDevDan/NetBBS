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

## Welcome banners

Sample ANSI welcome banners illustrating different aesthetic directions, color depths, and Unicode features, so a SysOp can switch a node over to a styled ANSI login screen right away:

### Truecolor (24-bit RGB) samples

- `welcome_banner_synthwave.ans` — **Synthwave / Cyberpunk Neon Grid:** features vibrant 24-bit RGB neon magenta-to-gold-to-cyan gradients, a chromatic sunset wordmark, a stylized half-block horizon perspective grid (`░▒▓█▀▄`), and modern rounded box-drawing (`╭─╮`).
- `welcome_banner_aurora.ans` — **Celestial Nebula / Aurora Borealis:** features deep astral violet-to-emerald aurora ribbons, starfield constellation accents (`✦ ✧ ★ ⋆ ✶`), double-line architectural framing (`╔═╗`), and a clean multi-column system telemetry layout.

### 256-color extended ANSI samples

- `welcome_banner_matrix.ans` — **Cyber Matrix / Green Phosphor:** features a high-contrast CRT green phosphor palette (shades 22–190), hexadecimal tech brackets (`⬡ ⬢ ⎔ ⏣`), segmented signal meters (`▰▰▰▱▱`), and fine scanline optical dithering.
- `welcome_banner_nord.ans` — **Nordic Frost / Polar Minimalist:** features ice cyan and slate blue accents (shades 31, 81, 117, 254), smooth rounded corners (`╭─╮`), diamond bullet hierarchies (`◆ ◇ ◈`), and discrete service pill badges.
- `welcome_banner_ember.ans` — **Ember Flame:** a double-line box-drawing border on black, with red/yellow gradient rules.
- `welcome_banner_classic.ans` — **Classic BBS Blue:** a plain-ASCII bordered box on a solid blue background (cyan/gold/magenta accents).

Neither is meant to be final — replace the placeholder `Node`/`SysOp` fields, or redraw the whole thing, before putting a node in front of real users.

**To use one:** `netbbs.net.welcome_banner` looks for a file at a well-known path colocated with the node's database — `<db-file-stem>_welcome_banner.ans`, e.g. `netbbs_welcome_banner.ans` next to `netbbs.db`. Copy whichever sample you want into place under that name:

```sh
cp examples/welcome_banner_synthwave.ans netbbs_welcome_banner.ans
```

Then enable it from the in-BBS SysOp admin menu (`[S]ysOp` → `[S]ystem` → `[W]elcome banner` → `[E]nable`), or from `python -m netbbs.admin` if the node isn't running yet. `[P]review` shows exactly what a connecting user would see; `[X] edit` opens the fullscreen WYSIWYG ANSI art editor against the current file and saves back to the same path directly — useful for tweaking one of these samples in place without touching the filesystem again.

All files are plain UTF-8 text containing real ANSI escape sequences (cursor positioning, SGR color codes) — view them with `cat` in a terminal that supports ANSI/VT100 sequences, not a plain text editor.

## Main-menu mastheads

`netbbs.net.main_menu_banner` (issue #161) offers the same mechanism as the welcome banner above, applied to a second, independent screen: an optional masthead shown directly above the main menu, which otherwise stays fully live and dynamic underneath (mail counts, per-user preferences, node status).

Sample mastheads are provided at compact heights (5–6 lines) with pixel-perfect 80-column alignment:

### Truecolor (24-bit RGB) mastheads

- `main_menu_banner_neon.ans` — **Neon Horizon Strip (6 lines):** a 24-bit Truecolor gradient horizontal banner with a glowing "NETBBS" micro-wordmark, chromatic sunset half-block ribbon (`░▒▓███▓▒░`), and quick-navigation service accents.
- `main_menu_banner_aurora.ans` — **Celestial Aurora Gateway (6 lines):** an astral violet-to-emerald gradient masthead with double-line brackets (`⟦ ⟧ ═ ║`), star accents (`★ ✦`), and live node telemetry indicators.

### 256-color extended ANSI mastheads

- `main_menu_banner_amber.ans` — **Retro Amber Arcade (6 lines):** warm copper and gold phosphor tones (shades 130–228), a segmented amber ribbon, and retro arcade-styled service badges.
- `main_menu_banner_nord.ans` — **Nordic Ice Clean (5 lines):** a distraction-free minimalist header with rounded framing (`╭─╮`), ice cyan text, and neat diamond divider rules (`◇ ── ◇`).

**To use one:** `netbbs.net.main_menu_banner` looks for a file at `<db-file-stem>_main_menu_banner.ans` next to `netbbs.db`. Copy whichever sample you want into place:

```sh
cp examples/main_menu_banner_neon.ans netbbs_main_menu_banner.ans
```

Then enable it from `[S]ysOp` → `[S]ystem` → `[M]asthead` → `[E]nable`. `[P]review` and `[X] edit` work the same way as the welcome banner's own screen.
