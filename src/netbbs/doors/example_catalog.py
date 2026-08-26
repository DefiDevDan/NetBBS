"""
Catalog of NetBBS's own bundled example doors (issue #172's `[G]allery`
follow-up for door registration, mirroring `netbbs.net.banner_presets`'
gallery pattern for welcome banners/mastheads).

**Deliberately not a repeat of `banner_presets`' own fix.** That module
exists precisely *because* `examples/` is excluded from the installed
wheel (`pyproject.toml`'s `[tool.setuptools.packages.find]` is scoped to
`src/` only) -- its answer was to migrate the actual sample bytes into
real installed package data so a wheel install has something to browse
at all. Doors are the opposite case, on purpose: `examples/README.md`
is explicit that a door script "genuinely *is* meant to be an external
program a SysOp points at" and deliberately stays a loose file, not
bundled data -- nothing about the door sandbox model expects NetBBS to
ship or run doors itself (design doc, issue #63/#167's locked sandbox
scope). So this module only ever carries *metadata about* the example
scripts (name, description, suggested play level) plus a resolver that
looks for the real file on disk relative to wherever this package
itself is running from -- it never bundles or reads door source.

That resolver only ever finds anything for a source checkout (the
`examples/doors/` directory sitting next to `src/`) -- for a wheel
install, `examples/` doesn't exist on disk at all, exactly the gap
`banner_presets` closed for banners and deliberately does *not* close
here. `available_example_doors()` reflects that by simply returning
fewer (or zero) entries, not by erroring -- the doors gallery screen's
own empty-list message is the honest answer for that case, not a
crash or a placeholder that pretends the file exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExampleDoor:
    key: str
    name: str
    description: str
    relative_path: str  # filename within examples/doors/
    suggested_min_play_level: int = 0


EXAMPLE_DOOR_CATALOG: tuple[ExampleDoor, ...] = (
    ExampleDoor(
        key="retro_trivia",
        name="Retro Trivia",
        description=(
            "Eight-question multiple-choice BBS trivia, single-keystroke A/B/C/D answers, "
            "a running score, and a colored final rank. Zero dependencies, session-scoped."
        ),
        relative_path="retro_trivia.py",
    ),
    ExampleDoor(
        key="voidrunner",
        name="Voidrunner",
        description=(
            "Persistent single-player space trading and exploration: a seeded galaxy with "
            "fog-of-war, a drifting per-system market, raider encounters, a mission board, "
            "faction reputation, and shipyard upgrades. Saves progress per caller."
        ),
        relative_path="voidrunner.py",
    ),
)


def _examples_doors_dir() -> Path:
    # this file: src/netbbs/doors/example_catalog.py
    #   .parent        -> src/netbbs/doors
    #   .parent.parent  -> src/netbbs
    #   .parent x3      -> src
    #   .parent x4      -> repo root
    return Path(__file__).resolve().parent.parent.parent.parent / "examples" / "doors"


def resolve_example_door_path(entry: ExampleDoor) -> Path | None:
    """The absolute path to `entry`'s script on this filesystem, or
    `None` if it isn't there (a wheel install with no `examples/`
    directory at all, or a source checkout missing that one file) --
    see this module's own docstring for why that's an expected,
    ungraceful-free outcome rather than an error."""
    path = _examples_doors_dir() / entry.relative_path
    return path if path.is_file() else None


def available_example_doors() -> list[tuple[ExampleDoor, Path]]:
    """Catalog entries whose script actually exists on this filesystem,
    paired with their resolved absolute path -- always empty for a
    wheel install, matching the same "needs a source checkout" ceiling
    every example door already has (see `examples/README.md`)."""
    resolved = []
    for entry in EXAMPLE_DOOR_CATALOG:
        path = resolve_example_door_path(entry)
        if path is not None:
            resolved.append((entry, path))
    return resolved
