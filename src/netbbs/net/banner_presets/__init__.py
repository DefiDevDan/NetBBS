"""
Bundled welcome-banner/masthead sample presets (issue #169).

Shipped as real installed package data -- the same mechanism `pyproject.
toml` already uses for `netbbs.web`'s own `static/*` -- specifically
because `examples/` (where these samples used to live) is *not* part of
the installed wheel at all: `[tool.setuptools.packages.find]` is scoped
to `src/` only. An operator running the actually-supported install path
(a release wheel, per `docs/NetBBS-operator-guide.md`) had no sample
files on their filesystem to `cp` into place in the first place -- the
gap this closes is bigger than "manual copying is annoying," it's "the
samples were unreachable from a real install."

`netbbs.net.admin_flow`'s `[G]allery` screens (welcome banner and
masthead) list these, preview one through the exact same preview call
the screen's own `[P]review` already uses, and apply it by writing its
bytes directly to `banner_path(db)`/`main_menu_banner_path(db)` -- zero
filesystem access needed, identical behavior for a wheel install or a
source checkout.

Descriptions originate from `examples/README.md`'s own former
"Welcome banners"/"Main-menu mastheads" sections, which described these
same samples as loose files before this module existed; that README
now just points here instead of duplicating the list.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class BannerPreset:
    key: str
    name: str
    depth: str  # "truecolor (24-bit RGB)" or "256-color extended ANSI"
    description: str
    resource: str  # filename within this package's welcome/ or masthead/ subdirectory


WELCOME_BANNER_PRESETS: tuple[BannerPreset, ...] = (
    BannerPreset(
        key="synthwave_magenta_cyan", name="Synthwave / Magenta-Cyan Neon Grid", depth="truecolor (24-bit RGB)",
        description=(
            "Vibrant 24-bit RGB neon magenta-to-gold-to-cyan gradients, a chromatic sunset "
            "wordmark, a stylized half-block horizon perspective grid (░▒▓█▀▄), and modern "
            "rounded box-drawing (╭─╮)."
        ),
        resource="synthwave_magenta_cyan.ans",
    ),
    BannerPreset(
        key="aurora_violet_emerald", name="Celestial Nebula / Violet-Emerald Aurora", depth="truecolor (24-bit RGB)",
        description=(
            "Deep astral violet-to-emerald aurora ribbons, starfield constellation accents "
            "(✦ ✧ ★ ⋆ ✶), double-line architectural framing (╔═╗), and a clean multi-column "
            "system telemetry layout."
        ),
        resource="aurora_violet_emerald.ans",
    ),
    BannerPreset(
        key="cyberpunk_sunset_gold", name="Cyberpunk Megacity / Sunset Amber-Gold", depth="truecolor (24-bit RGB)",
        description=(
            "High-saturation blood orange to sunset amber gradient horizon with half-block "
            "skyline silhouette (▀▄█), segmented telemetry HUD, and heavy border brackets (┏━┓)."
        ),
        resource="cyberpunk_sunset_gold.ans",
    ),
    BannerPreset(
        key="deep_ocean_sapphire_teal", name="Abyssal Ocean / Sapphire-Teal", depth="truecolor (24-bit RGB)",
        description=(
            "Sub-surface ocean mesh theme with deep navy to bioluminescent teal gradients, "
            "wave crest artwork, oceanic telemetry badges, and clean rounded frames (╭─╮)."
        ),
        resource="deep_ocean_sapphire_teal.ans",
    ),
    BannerPreset(
        key="solar_flare_crimson_amber", name="Solar Flare / Crimson-Amber Supernova", depth="truecolor (24-bit RGB)",
        description=(
            "High-intensity solar prominence arches, supernova crimson-to-gold plasma gradients, "
            "fusion core metrics, and glowing dither pulse bars (░▒▓█▓▒░)."
        ),
        resource="solar_flare_crimson_amber.ans",
    ),
    BannerPreset(
        key="matrix_phosphor_green", name="Cyber Matrix / Green Phosphor CRT", depth="256-color extended ANSI",
        description=(
            "High-contrast CRT green phosphor palette (shades 22-190), hexadecimal tech "
            "brackets (⬡ ⬢ ⎔ ⏣), segmented signal meters (▰▰▰▱▱), and fine scanline optical "
            "dithering."
        ),
        resource="matrix_phosphor_green.ans",
    ),
    BannerPreset(
        key="nord_frost_slate", name="Nordic Frost / Polar Slate & Cyan", depth="256-color extended ANSI",
        description=(
            "Ice cyan and slate blue accents (shades 31, 81, 117, 254), smooth rounded corners "
            "(╭─╮), diamond bullet hierarchies (◆ ◇ ◈), and discrete service pill badges."
        ),
        resource="nord_frost_slate.ans",
    ),
    BannerPreset(
        key="dracula_purple_pink", name="Dracula Night / Purple & Neon Pink", depth="256-color extended ANSI",
        description=(
            "Gothic modern dark mode aesthetic with Dracula purple (141), neon pink (212), "
            "vampire telemetry, bat/star accents (❖ ✦), and double-line framing (╔═╗)."
        ),
        resource="dracula_purple_pink.ans",
    ),
    BannerPreset(
        key="tokyo_night_storm", name="Tokyo Night / Shibuya Cyan-Magenta", depth="256-color extended ANSI",
        description=(
            "Tokyo metropolis cyber grid with deep navy (236), bright cyan (51), electric "
            "magenta (198), Japanese terminal brackets (⟦ 東京 ⟧), and optical scanline dithers."
        ),
        resource="tokyo_night_storm.ans",
    ),
    BannerPreset(
        key="amber_monochrome_arcade", name="Vintage Mainframe / Warm Amber CRT", depth="256-color extended ANSI",
        description=(
            "Classic 1980s monochrome computing aura in warm amber & gold phosphor (shades 130-228), "
            "double-line mainframe framing, and retro baud status badges."
        ),
        resource="amber_monochrome_arcade.ans",
    ),
    BannerPreset(
        key="ember_crimson_gold", name="Ember Flame / Crimson & Gold", depth="256-color extended ANSI",
        description="A double-line box-drawing border on black, with red/yellow flame gradient rules.",
        resource="ember_crimson_gold.ans",
    ),
    BannerPreset(
        key="classic_terminal_blue", name="Classic BBS / Solid Blue & Cyan", depth="256-color extended ANSI",
        description="A plain bordered box on a solid blue background (cyan/gold/magenta accents).",
        resource="classic_terminal_blue.ans",
    ),
    BannerPreset(
        key="outrun_sunset_grid", name="Outrun 80s Grid / Pink-Orange-Yellow", depth="truecolor (24-bit RGB)",
        description=(
            "Synthwave high-speed vector sun silhouette, road perspective grid, and Outrun highway typography."
        ),
        resource="outrun_sunset_grid.ans",
    ),
    BannerPreset(
        key="emerald_matrix_digital_rain", name="Bioluminescent Emerald / Matrix Rain", depth="truecolor (24-bit RGB)",
        description=(
            "Organic neural rainforest canopy with cascading digital droplet vines, biocores, and mint plasma."
        ),
        resource="emerald_matrix_digital_rain.ans",
    ),
    BannerPreset(
        key="vaporwave_pastel_dream", name="Vaporwave Dream / Pastel Lilac-Peach", depth="truecolor (24-bit RGB)",
        description=(
            "Soothing pastel lilac, sky azure, and peach aesthetic with Greek marble columns and Japanese typography."
        ),
        resource="vaporwave_pastel_dream.ans",
    ),
    BannerPreset(
        key="crimson_samurai_cyber", name="Cyber Samurai / Crimson & Gold Leaf", depth="truecolor (24-bit RGB)",
        description=(
            "Kyoto cyber-citadel aesthetic with katana blade divider, torii gate architecture, and crimson sun."
        ),
        resource="crimson_samurai_cyber.ans",
    ),
    BannerPreset(
        key="glacier_aurora_ice", name="Glacial Crystal / Arctic Cyan-White", depth="truecolor (24-bit RGB)",
        description=(
            "Sub-zero cryogenic polar vault theme with crystalline snowflake fractals and frost diamond framing."
        ),
        resource="glacier_aurora_ice.ans",
    ),
    BannerPreset(
        key="gruvbox_warm_retro", name="Gruvbox Retro / Warm Yellow-Orange", depth="256-color extended ANSI",
        description=(
            "Warm earthy retro terminal palette with typewriter block headers, cozy mechanical borders, and signal meters."
        ),
        resource="gruvbox_warm_retro.ans",
    ),
    BannerPreset(
        key="solarized_dark_cyan", name="Solarized Dark / Scientific Cyan-Blue", depth="256-color extended ANSI",
        description=(
            "Precision IEEE engineering standard with crisp drafting borders, deterministic states, and clean alignment."
        ),
        resource="solarized_dark_cyan.ans",
    ),
    BannerPreset(
        key="catppuccin_mocha_lavender", name="Catppuccin Mocha / Lavender & Mauve", depth="256-color extended ANSI",
        description=(
            "Cozy pastel dark mode with mocha crust, lavender typography, pastel pill badges, and soft dither ribbon."
        ),
        resource="catppuccin_mocha_lavender.ans",
    ),
    BannerPreset(
        key="monokai_pro_vivid", name="Monokai Pro / Vivid Hacker Syntax", depth="256-color extended ANSI",
        description=(
            "High-contrast code syntax aesthetic with vivid pink, lime green, yellow keywords, and JSON status headers."
        ),
        resource="monokai_pro_vivid.ans",
    ),
    BannerPreset(
        key="c64_nostalgia_cyan", name="Commodore 64 / 8-Bit Vintage Blue", depth="256-color extended ANSI",
        description=(
            "Authentic 1982 C64 startup screen recreation with PETSCII borders, 38911 bytes free prompt, and blinking cursor."
        ),
        resource="c64_nostalgia_cyan.ans",
    ),
)

MAIN_MENU_BANNER_PRESETS: tuple[BannerPreset, ...] = (
    BannerPreset(
        key="neon_magenta_cyan", name="Neon Horizon Strip / Magenta-Cyan", depth="truecolor (24-bit RGB)",
        description=(
            "A 24-bit Truecolor gradient horizontal banner (6 lines) with a glowing \"NETBBS\" "
            "micro-wordmark, chromatic sunset half-block ribbon (░▒▓███▓▒░), and quick-"
            "navigation service accents."
        ),
        resource="neon_magenta_cyan.ans",
    ),
    BannerPreset(
        key="aurora_violet_emerald", name="Celestial Aurora Gateway / Violet-Emerald", depth="truecolor (24-bit RGB)",
        description=(
            "An astral violet-to-emerald gradient masthead (6 lines) with double-line brackets "
            "(⟦ ⟧ ═ ║), star accents (★ ✦), and live node telemetry indicators."
        ),
        resource="aurora_violet_emerald.ans",
    ),
    BannerPreset(
        key="sunset_orange_purple", name="Cyber Sunset / Orange & Purple", depth="truecolor (24-bit RGB)",
        description=(
            "Vivid sunset magenta to amber-gold header (6 lines) with heavy block frames (┏━┓), "
            "gradient mesh status, and compact service navigation pills."
        ),
        resource="sunset_orange_purple.ans",
    ),
    BannerPreset(
        key="deep_ocean_sapphire_aqua", name="Abyssal Crest / Sapphire & Aqua", depth="truecolor (24-bit RGB)",
        description=(
            "Deep ocean oceanic header (6 lines) with sapphire-to-aqua half-block dividing "
            "rules and crystal-clear service navigation."
        ),
        resource="deep_ocean_sapphire_aqua.ans",
    ),
    BannerPreset(
        key="solar_flare_gold_crimson", name="Solar Prominence / Gold & Crimson", depth="truecolor (24-bit RGB)",
        description=(
            "Supernova energy header (6 lines) with molten crimson-to-gold dither pulse bar "
            "and illuminated service badges."
        ),
        resource="solar_flare_gold_crimson.ans",
    ),
    BannerPreset(
        key="amber_warm_gold", name="Retro Amber Arcade / Warm Gold", depth="256-color extended ANSI",
        description=(
            "Warm copper and gold phosphor tones (shades 130-228, 6 lines), a segmented amber "
            "ribbon, and retro arcade-styled service badges."
        ),
        resource="amber_warm_gold.ans",
    ),
    BannerPreset(
        key="nord_frost_ice", name="Nordic Ice Clean / Slate & Frost", depth="256-color extended ANSI",
        description=(
            "A distraction-free minimalist header (5 lines) with rounded framing (╭─╮), ice "
            "cyan text, and neat diamond divider rules (◇ ── ◇)."
        ),
        resource="nord_frost_ice.ans",
    ),
    BannerPreset(
        key="matrix_phosphor_green", name="Matrix Cyber Relay / Phosphor Green", depth="256-color extended ANSI",
        description=(
            "Matrix green phosphor header (6 lines) with technical square brackets, scanline "
            "optical dithering, and cyber green navigation tags."
        ),
        resource="matrix_phosphor_green.ans",
    ),
    BannerPreset(
        key="dracula_purple_cyan", name="Dracula Ribbon / Purple & Cyan", depth="256-color extended ANSI",
        description=(
            "Dracula vampire theme header (6 lines) with purple-to-pink gradient dither ribbon "
            "and dark mode pastel navigation pills."
        ),
        resource="dracula_purple_cyan.ans",
    ),
    BannerPreset(
        key="tokyo_night_magenta_cyan", name="Tokyo Night / Shibuya Cyan-Magenta", depth="256-color extended ANSI",
        description=(
            "Tokyo metropolis cyber header (6 lines) with Japanese brackets (⟦ 東京 ⟧), "
            "high-tech status line, and crisp service matrix."
        ),
        resource="tokyo_night_magenta_cyan.ans",
    ),
    BannerPreset(
        key="outrun_sunset_strip", name="Outrun Sunset Strip / Pink-Orange", depth="truecolor (24-bit RGB)",
        description="6-line high-speed synthwave horizon with vector sunset ribbon and turbo navigation tags.",
        resource="outrun_sunset_strip.ans",
    ),
    BannerPreset(
        key="emerald_matrix_strip", name="Bio-Emerald Masthead / Jade-Mint", depth="truecolor (24-bit RGB)",
        description="6-line bioluminescent rainforest stream with neural telemetry badges and half-block emerald divider.",
        resource="emerald_matrix_strip.ans",
    ),
    BannerPreset(
        key="vaporwave_pastel_strip", name="Vaporwave Pastel Strip / Lilac-Sky", depth="truecolor (24-bit RGB)",
        description="6-line aesthetic Japanese pastel header with marble checkerboard rule and breezy typography.",
        resource="vaporwave_pastel_strip.ans",
    ),
    BannerPreset(
        key="crimson_samurai_strip", name="Cyber Samurai Blade / Crimson-Gold", depth="truecolor (24-bit RGB)",
        description="6-line shadow relay header with torii gate icons, katana blade ribbon, and dojo navigation.",
        resource="crimson_samurai_strip.ans",
    ),
    BannerPreset(
        key="glacier_crystal_strip", name="Glacial Crystal Header / Frost Cyan", depth="truecolor (24-bit RGB)",
        description="6-line cryogenic arctic header with snowflake diamond markers and ice crystal half-block rule.",
        resource="glacier_crystal_strip.ans",
    ),
    BannerPreset(
        key="gruvbox_retro_header", name="Gruvbox Retro Header / Warm Gold", depth="256-color extended ANSI",
        description="6-line mechanical console header with warm amber-to-green dither meter and retro arcade tabs.",
        resource="gruvbox_retro_header.ans",
    ),
    BannerPreset(
        key="solarized_technical_header", name="Solarized Technical / Clean Cyan", depth="256-color extended ANSI",
        description="5-line precision drafting header with IEEE telemetry badges and compact service grid.",
        resource="solarized_technical_header.ans",
    ),
    BannerPreset(
        key="catppuccin_mocha_header", name="Catppuccin Mocha Header / Lavender", depth="256-color extended ANSI",
        description="6-line cozy pastel header with lavender-to-mauve dither ribbon and rounded dark mode pill badges.",
        resource="catppuccin_mocha_header.ans",
    ),
    BannerPreset(
        key="monokai_pro_header", name="Monokai Pro Header / Vivid Code", depth="256-color extended ANSI",
        description="6-line syntax-highlighted code header with JSON status block and monospace navigation prompts.",
        resource="monokai_pro_header.ans",
    ),
    BannerPreset(
        key="c64_vintage_header", name="Commodore 64 Masthead / Vintage Blue", depth="256-color extended ANSI",
        description="5-line authentic 8-bit PETSCII header with solid C64 blue background and retro command prompt.",
        resource="c64_vintage_header.ans",
    ),
)


def load_welcome_banner_preset(preset: BannerPreset) -> bytes:
    return (resources.files(__package__) / "welcome" / preset.resource).read_bytes()


def load_main_menu_banner_preset(preset: BannerPreset) -> bytes:
    return (resources.files(__package__) / "masthead" / preset.resource).read_bytes()
