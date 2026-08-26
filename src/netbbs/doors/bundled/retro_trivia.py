#!/usr/bin/env python3
"""
Retro Trivia -- a real, playable door game for NetBBS (issue #172).

A genuine proof-of-concept for the native door-game vertical, not a
throwaway test fixture: reads the v1 drop-file (see `netbbs.doors.
runtime`'s own module docstring) for the caller's handle, color depth,
and node name; talks single raw bytes over stdin/stdout for the whole
session -- no line-editing help from NetBBS, a door owns its own raw
terminal stream once launched, which is exactly why every answer here
is a single keystroke (A/B/C/D), not a typed line this script would
otherwise have to implement its own backspace/editing for.

Runnable completely standalone too, outside NetBBS entirely
(`python3 retro_trivia.py` from a real terminal) -- every drop-file
field falls back to a sane default if `NETBBS_DOOR_INFO` is unset or
unreadable, so a SysOp (or anyone) can try it before ever registering
it as a door.

Zero external dependencies -- stdlib only, so "python3" plus this
file's path is the entire executable_path/args a SysOp needs to
register (see examples/README.md for the exact registration steps).
"""

from __future__ import annotations

import json
import os
import random
import sys

ESC = "\x1b"
RESET = f"{ESC}[0m"
BOLD = f"{ESC}[1m"


def _load_door_info() -> dict:
    default = {
        "handle": "Guest",
        "user_id": 0,
        "terminal_width": 80,
        "terminal_height": 24,
        "color_depth": "256",
        "node_name": "NetBBS",
    }
    path = os.environ.get("NETBBS_DOOR_INFO")
    if not path:
        return default
    try:
        with open(path, encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        return default
    default.update(info)
    return default


class Palette:
    """Two depths of the same handful of named colors -- truecolor RGB
    triples, and their nearest hand-picked xterm 256 equivalents. A real
    nearest-256 algorithm is overkill for the six colors this door
    actually uses."""

    def __init__(self, truecolor: bool):
        self._truecolor = truecolor

    def _sgr(self, rgb: tuple[int, int, int], idx256: int) -> str:
        if self._truecolor:
            r, g, b = rgb
            return f"{ESC}[38;2;{r};{g};{b}m"
        return f"{ESC}[38;5;{idx256}m"

    @property
    def title(self) -> str:
        return self._sgr((255, 90, 190), 205)

    @property
    def accent(self) -> str:
        return self._sgr((100, 220, 255), 51)

    @property
    def correct(self) -> str:
        return self._sgr((110, 255, 130), 46)

    @property
    def wrong(self) -> str:
        return self._sgr((255, 100, 100), 203)

    @property
    def muted(self) -> str:
        return self._sgr((150, 150, 160), 244)

    @property
    def gold(self) -> str:
        return self._sgr((255, 200, 60), 220)


def out(text: str = "") -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def out_line(text: str = "") -> None:
    out(text + "\r\n")


def read_key() -> str:
    """One raw byte -- see this module's own docstring for why that's
    all a door gets. A caller disconnecting mid-question doesn't reach
    the `except EOFError` below in the common case (NetBBS's own runtime
    just SIGTERMs this process directly once the relay notices) -- kept
    anyway for the rarer case of stdin closing gracefully first."""
    data = sys.stdin.buffer.read(1)
    if not data:
        raise EOFError("stdin closed")
    return data.decode("ascii", errors="replace")


QUESTIONS = [
    # (question, choices A-D, correct index 0-3)
    ("What decade did the first public dial-up BBS go online?", ["1960s", "1970s", "1980s", "1990s"], 1),
    ("Which protocol lets a caller resume an interrupted file transfer?", ["FTP", "Zmodem", "Gopher", "NNTP"], 1),
    ("What does 'SysOp' stand for?", ["System Operator", "Synchronous Option", "System Optimizer", "Sync Operator"], 0),
    ("Which of these is a classic terminal emulation standard?", ["ANSI", "JPEG", "SMTP", "DNS"], 0),
    ("What's the standard terminal width most BBS art was drawn for?", ["40 columns", "60 columns", "80 columns", "132 columns"], 2),
    ("Which layer of the OSI model does Telnet operate at?", ["Physical", "Transport", "Application", "Network"], 2),
    ("What does 'FTN' commonly refer to in BBS history?", ["File Transfer Node", "FidoNet Technology Network", "Fast Terminal Negotiation", "FidoNet-compatible Networks"], 3),
    ("Which of these predates the modern internet as a store-and-forward network?", ["FidoNet", "BitTorrent", "IRC", "XMPP"], 0),
    ("A 'door game' on a BBS most commonly refers to what?", ["A hardware lock", "An external program callers could run", "A locked message board", "A dial-up busy signal"], 1),
    ("What's the usual name for the file that gives a DOS door caller info?", ["INFO.TXT", "DOOR.SYS", "CALLER.LOG", "SETUP.INI"], 1),
    ("Which of these is a real-time chat protocol, not a message-board one?", ["NNTP", "IRC", "UUCP", "POP3"], 1),
    ("What's a node's opening screen at login usually called?", ["A welcome banner", "A drop file", "A packet header", "A nodelist"], 0),
    ("Which number base do 256-color ANSI codes use per channel?", ["Binary", "Octal", "Decimal", "Hexadecimal"], 2),
    ("What's the classic BBS term for a caller's very first visit?", ["A new user", "A guest login", "A cold call", "A first-timer"], 0),
    ("SSH primarily improves on Telnet by adding what?", ["Faster transfer speed", "Encryption", "Color support", "File attachments"], 1),
]

QUESTIONS_PER_ROUND = 8
LETTERS = ["A", "B", "C", "D"]


def draw_title(p: Palette, info: dict) -> None:
    out_line()
    out_line(f"{p.title}{BOLD}╔═════════════════════════════════════════════╗{RESET}")
    out_line(f"{p.title}{BOLD}║{RESET}          {p.gold}{BOLD}R E T R O   T R I V I A{RESET}          {p.title}{BOLD}║{RESET}")
    out_line(f"{p.title}{BOLD}╚════════════════════════════════════════════╝{RESET}")
    out_line()
    out_line(f"{p.muted}Welcome, {RESET}{p.accent}{BOLD}{info['handle']}{RESET}{p.muted}, to {info['node_name']}'s trivia challenge.{RESET}")
    out_line(f"{p.muted}Answer with A, B, C, or D -- no Enter needed.{RESET}")
    out_line()


def ask_question(p: Palette, number: int, total: int, question: str, choices: list[str]) -> int:
    out_line(f"{p.accent}{BOLD}Question {number}/{total}{RESET}  {question}")
    for letter, choice in zip(LETTERS, choices):
        out_line(f"  {p.gold}{BOLD}[{letter}]{RESET} {choice}")
    out(f"{p.muted}Your answer: {RESET}")
    while True:
        key = read_key().upper()
        if key in LETTERS:
            out_line(key)
            return LETTERS.index(key)
        # Anything else (stray bytes, arrow-key escape fragments, etc.)
        # is just ignored -- this game only ever listens for A-D.


def draw_result(p: Palette, correct: bool, answer: str) -> None:
    if correct:
        out_line(f"{p.correct}{BOLD}Correct!{RESET}")
    else:
        out_line(f"{p.wrong}{BOLD}Not quite.{RESET} {p.muted}The answer was {answer}.{RESET}")
    out_line()


def rank_for(score: int, total: int) -> str:
    pct = score / total
    if pct == 1.0:
        return "SysOp material"
    if pct >= 0.75:
        return "Seasoned caller"
    if pct >= 0.5:
        return "Getting there"
    return "Newbie"


def draw_final_score(p: Palette, score: int, total: int) -> None:
    rule = f"{p.title}{BOLD}" + "─" * 50 + RESET
    out_line(rule)
    out_line(f"{p.gold}{BOLD}Final score: {score}/{total}{RESET}  ({rank_for(score, total)})")
    out_line(rule)
    out_line()
    out_line(f"{p.muted}Thanks for playing. Press any key to leave...{RESET}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    info = _load_door_info()
    palette = Palette(truecolor=info.get("color_depth") == "truecolor")

    draw_title(palette, info)

    round_questions = random.sample(QUESTIONS, k=min(QUESTIONS_PER_ROUND, len(QUESTIONS)))
    score = 0
    try:
        for i, (question, choices, correct_index) in enumerate(round_questions, start=1):
            chosen = ask_question(palette, i, len(round_questions), question, choices)
            correct = chosen == correct_index
            if correct:
                score += 1
            draw_result(palette, correct, f"{LETTERS[correct_index]}) {choices[correct_index]}")

        draw_final_score(palette, score, len(round_questions))
        read_key()
    except EOFError:
        return 0
    finally:
        out(RESET)
    return 0


if __name__ == "__main__":
    sys.exit(main())
