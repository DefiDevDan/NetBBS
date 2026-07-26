"""
Per-character color gradients across a short string (e.g. a caller's
displayed name), the flair seen in MUD "who" lists this was modeled on.

Built on top of `netbbs.rendering.ansi.colored()`'s truecolor tuple
support (`fg_rgb`), never a hand-built escape string -- so the same
"always reset, never emit an empty escape" guarantee `colored()` already
gives every other caller in this package applies here too. Follows
`netbbs.rendering.reflow.colored_truncate`'s composition shape: one
`colored()` call per colored span, concatenated -- adjacent characters
that resolve to the same color are coalesced into a single span (the
same change-detection idea `netbbs.rendering.ansi_art.encode_ansi_bytes`
uses row-by-row) so escape-sequence count doesn't scale one-for-one with
character count whenever consecutive interpolation steps round alike.

`text` is untrusted content (same tier as anything else displayed on a
caller-facing screen) and is always passed through
`netbbs.rendering.sanitize.sanitize_text` first, per that module's
"sanitize the untrusted piece before styling" convention.
"""

from __future__ import annotations

from typing import Sequence

from netbbs.rendering.ansi import colored
from netbbs.rendering.sanitize import sanitize_text

#: Named gradient presets, each a list of 2+ `(r, g, b)` stops
#: interpolated piecewise-linearly across a string's length. Callers
#: aren't limited to these -- `gradient_text`'s `gradient` argument also
#: accepts an arbitrary caller-supplied stop list.
GRADIENTS: dict[str, list[tuple[int, int, int]]] = {
    "red": [(255, 0, 0), (139, 0, 0)],
    "blue": [(0, 0, 255), (0, 255, 255)],
    "gold": [(255, 215, 0), (139, 69, 19)],
}


def gradient_text(
    text: str,
    gradient: str | Sequence[tuple[int, int, int]],
    *,
    bold: bool = False,
    truecolor: bool = True,
) -> str:
    """
    Color each character of `text` along `gradient`, interpolating
    piecewise-linearly across its RGB stops.

    `gradient` is either a preset name from `GRADIENTS` or a
    caller-supplied sequence of 2+ `(r, g, b)` stops -- 3+ stops give a
    multi-stop gradient (e.g. red -> white -> dark red) for free, since
    interpolation happens independently between each consecutive pair.

    `truecolor` selects which color depth is actually emitted: `True`
    (the default) sends real 24-bit RGB and must only be used for a
    session confirmed to support it (see
    `netbbs.net.session.Session.supports_truecolor`, or
    `netbbs.net.color_depth_preference.effective_truecolor` once a
    caller is logged in); `False` converts every interpolated color to
    its nearest 256-palette index instead, so a caller never has to
    hand-roll its own downgrade path.
    """
    text = sanitize_text(text)
    if not text:
        return ""

    if isinstance(gradient, str):
        if gradient not in GRADIENTS:
            raise ValueError(
                f"unknown gradient {gradient!r}, expected one of {sorted(GRADIENTS)} "
                "or an explicit list of (r, g, b) stops"
            )
        stops = GRADIENTS[gradient]
    else:
        stops = list(gradient)
    if len(stops) < 2:
        raise ValueError(f"gradient needs at least 2 stops, got {len(stops)}")
    for r, g, b in stops:
        _validate_stop(r, g, b)

    colors: list[int | tuple[int, int, int]] = []
    for i in range(len(text)):
        t = i / (len(text) - 1) if len(text) > 1 else 0.0
        rgb = _interpolate(stops, t)
        colors.append(rgb if truecolor else _nearest_256(rgb))

    spans: list[str] = []
    run_start = 0
    for i in range(1, len(text) + 1):
        if i < len(text) and colors[i] == colors[run_start]:
            continue
        spans.append(colored(text[run_start:i], fg_color=colors[run_start], bold=bold))
        run_start = i
    return "".join(spans)


def _validate_stop(r: int, g: int, b: int) -> None:
    for name, value in (("r", r), ("g", g), ("b", b)):
        if not 0 <= value <= 255:
            raise ValueError(f"gradient stop {name} must be 0-255, got {value}")


def _interpolate(
    stops: Sequence[tuple[int, int, int]], t: float
) -> tuple[int, int, int]:
    segments = len(stops) - 1
    position = t * segments
    index = min(int(position), segments - 1)
    local_t = position - index
    r0, g0, b0 = stops[index]
    r1, g1, b1 = stops[index + 1]
    return (
        round(r0 + (r1 - r0) * local_t),
        round(g0 + (g1 - g0) * local_t),
        round(b0 + (b1 - b0) * local_t),
    )


#: xterm 256-palette color-cube levels (indices 16-231): each of r/g/b
#: independently takes one of these 6 values.
_CUBE_LEVELS = (0, 95, 135, 175, 215, 255)


def _nearest_256(rgb: tuple[int, int, int]) -> int:
    """
    Nearest xterm-256 palette index to `rgb`, by squared Euclidean
    distance -- the standard truecolor-to-256 downgrade algorithm
    (compare against both the 6x6x6 color cube and the 24-step
    grayscale ramp, keep whichever candidate is closer), used here
    rather than the 16-color basic palette since every other 256-color
    call site in this codebase already assumes the richer cube/ramp
    range (`netbbs.rendering.ansi`'s module docstring).
    """
    r, g, b = rgb

    def nearest_level(v: int) -> int:
        return min(range(6), key=lambda i: abs(_CUBE_LEVELS[i] - v))

    r_i, g_i, b_i = nearest_level(r), nearest_level(g), nearest_level(b)
    cube_color = (_CUBE_LEVELS[r_i], _CUBE_LEVELS[g_i], _CUBE_LEVELS[b_i])
    cube_index = 16 + 36 * r_i + 6 * g_i + b_i
    cube_distance = _squared_distance(rgb, cube_color)

    gray_levels = [8 + 10 * i for i in range(24)]
    gray_i = min(range(24), key=lambda i: abs(gray_levels[i] - sum(rgb) / 3))
    gray_value = gray_levels[gray_i]
    gray_distance = _squared_distance(rgb, (gray_value, gray_value, gray_value))

    return cube_index if cube_distance <= gray_distance else 232 + gray_i


def _squared_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return sum((x - y) ** 2 for x, y in zip(a, b))
