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

Sample ANSI welcome banners illustrating different aesthetic directions, color depths, and modern Unicode features. All samples are designed for standard 80-column terminal displays and can be deployed directly or previewed in-BBS.

### Truecolor (24-bit RGB) welcome banners

- `welcome_banner_truecolor_synthwave_magenta_cyan.ans` — **Synthwave Neon Grid:** features vibrant 24-bit RGB neon magenta-to-gold-to-cyan gradients, a chromatic sunset wordmark, a stylized half-block horizon perspective grid (`░▒▓█▀▄`), and modern rounded box-drawing (`╭─╮`).
- `welcome_banner_truecolor_aurora_violet_emerald.ans` — **Celestial Aurora:** features deep astral violet-to-emerald aurora ribbons, starfield constellation accents (`✦ ✧ ★ ⋆ ✶`), double-line architectural framing (`╔═╗`), and a clean multi-column system telemetry layout.
- `welcome_banner_truecolor_cyberpunk_sunset_gold.ans` — **Cyberpunk Megacity:** features a blood orange to sunset amber gradient horizon, a half-block skyline silhouette (`▀▄█`), segmented telemetry HUD, and heavy border brackets (`┏━┓`).
- `welcome_banner_truecolor_deep_ocean_sapphire_teal.ans` — **Abyssal Ocean:** sub-surface oceanic mesh theme with deep navy to bioluminescent teal gradients, wave crest artwork, oceanic telemetry badges, and clean rounded frames (`╭─╮`).
- `welcome_banner_truecolor_solar_flare_crimson_amber.ans` — **Solar Flare Supernova:** high-intensity solar prominence flame arches, supernova crimson-to-gold plasma gradients, fusion core metrics, and glowing dither pulse bars (`░▒▓█▓▒░`).

### 256-color extended ANSI welcome banners

- `welcome_banner_256_matrix_phosphor_green.ans` — **Cyber Matrix CRT:** features a high-contrast green phosphor CRT palette (shades 22–190), hexadecimal tech brackets (`⬡ ⬢ ⎔ ⏣`), segmented signal meters (`▰▰▰▱▱`), and fine scanline optical dithering.
- `welcome_banner_256_nord_frost_slate.ans` — **Nordic Frost:** features ice cyan and slate blue accents (shades 31, 81, 117, 254), smooth rounded corners (`╭─╮`), diamond bullet hierarchies (`◆ ◇ ◈`), and discrete service pill badges.
- `welcome_banner_256_dracula_purple_pink.ans` — **Dracula Dark Mode:** gothic modern dark aesthetic with Dracula purple (141), neon pink (212), vampire telemetry, bat/star accents (`❖ ✦`), and double-line framing (`╔═╗`).
- `welcome_banner_256_tokyo_night_storm.ans` — **Tokyo Night Cyberpunk:** Tokyo metropolis cyber grid with deep navy (236), bright cyan (51), electric magenta (198), Japanese terminal brackets (`⟦ 東京 ⟧`), and optical scanline dithers.
- `welcome_banner_256_amber_monochrome_arcade.ans` — **Vintage Amber Mainframe:** classic 1980s monochrome computing aura in warm amber & gold phosphor (shades 130–228), double-line mainframe framing, and retro baud status badges.
- `welcome_banner_256_ember_crimson_gold.ans` — **Ember Flame:** a double-line box-drawing border on black, with red/yellow flame gradient rules.
- `welcome_banner_256_classic_terminal_blue.ans` — **Classic BBS Blue:** a plain bordered box on a solid blue background (cyan/gold/magenta accents).

**To use one:** `netbbs.net.welcome_banner` looks for a file at `<db-file-stem>_welcome_banner.ans` next to `netbbs.db`. Copy whichever sample you want into place:

```sh
cp examples/welcome_banner_truecolor_synthwave_magenta_cyan.ans netbbs_welcome_banner.ans
```

Then enable it from the in-BBS SysOp admin menu (`[S]ysOp` → `[S]ystem` → `[W]elcome banner` → `[E]nable` or choose `[G]allery` to pick from bundled presets), or from `python -m netbbs.admin` if the node isn't running yet. `[P]review` shows exactly what a connecting user would see; `[X] edit` opens the fullscreen WYSIWYG ANSI art editor against the current file.

All files are UTF-8 encoded text containing standard ANSI escapes — view them with `cat` in an ANSI-capable terminal.

## Main-menu mastheads

`netbbs.net.main_menu_banner` (issue #161) offers optional header art displayed directly above the authenticated main menu while keeping all dynamic elements (mail count, per-user preferences, node status) active underneath.

Sample mastheads are compact (5–6 lines) with pixel-perfect 80-column alignment:

### Truecolor (24-bit RGB) mastheads

- `main_menu_banner_truecolor_neon_magenta_cyan.ans` — **Neon Horizon Strip (6 lines):** a 24-bit Truecolor gradient horizontal banner with a glowing "NETBBS" micro-wordmark, chromatic sunset half-block ribbon (`░▒▓███▓▒░`), and quick-navigation service accents.
- `main_menu_banner_truecolor_aurora_violet_emerald.ans` — **Celestial Aurora Gateway (6 lines):** an astral violet-to-emerald gradient masthead with double-line brackets (`⟦ ⟧ ═ ║`), star accents (`★ ✦`), and live node telemetry indicators.
- `main_menu_banner_truecolor_sunset_orange_purple.ans` — **Cyber Sunset (6 lines):** vivid sunset magenta to amber-gold header with heavy block frames (`┏━┓`), gradient mesh status, and compact service navigation pills.
- `main_menu_banner_truecolor_deep_ocean_sapphire_aqua.ans` — **Abyssal Crest (6 lines):** deep ocean oceanic header with sapphire-to-aqua half-block dividing rules and crystal-clear service navigation.
- `main_menu_banner_truecolor_solar_flare_gold_crimson.ans` — **Solar Prominence (6 lines):** supernova energy header with molten crimson-to-gold dither pulse bar and illuminated service badges.

### 256-color extended ANSI mastheads

- `main_menu_banner_256_amber_warm_gold.ans` — **Retro Amber Arcade (6 lines):** warm copper and gold phosphor tones (shades 130–228), a segmented amber ribbon, and retro arcade-styled service badges.
- `main_menu_banner_256_nord_frost_ice.ans` — **Nordic Ice Clean (5 lines):** a distraction-free minimalist header with rounded framing (`╭─╮`), ice cyan text, and neat diamond divider rules (`◇ ── ◇`).
- `main_menu_banner_256_matrix_phosphor_green.ans` — **Matrix Cyber Relay (6 lines):** matrix green phosphor header with technical square brackets, scanline optical dithering, and cyber green navigation tags.
- `main_menu_banner_256_dracula_purple_cyan.ans` — **Dracula Ribbon (6 lines):** Dracula vampire theme header with purple-to-pink gradient dither ribbon and dark mode pastel navigation pills.
- `main_menu_banner_256_tokyo_night_magenta_cyan.ans` — **Tokyo Night (6 lines):** Tokyo metropolis cyber header with Japanese brackets (`⟦ 東京 ⟧`), high-tech status line, and crisp service matrix.

**To use one:** `netbbs.net.main_menu_banner` looks for a file at `<db-file-stem>_main_menu_banner.ans` next to `netbbs.db`. Copy whichever sample you want into place:

```sh
cp examples/main_menu_banner_truecolor_neon_magenta_cyan.ans netbbs_main_menu_banner.ans
```

Then enable it from `[S]ysOp` → `[S]ystem` → `[M]asthead` → `[E]nable` (or browse `[G]allery`). `[P]review` and `[X] edit` work the same way as the welcome banner screen.
