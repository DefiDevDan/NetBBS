"""Tests for netbbs.net.session's Session base class defaults."""

from __future__ import annotations

from netbbs.net.session import Session


def test_supports_truecolor_defaults_to_false():
    assert Session.supports_truecolor is False
