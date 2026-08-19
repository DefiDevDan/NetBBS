# NetBBS v5.0.1

A patch release fixing gaps found during ongoing dogfood/Link
deployment prep. No schema migration, no protocol change, no new
config surface.

## Fixes

- **Link now works behind a forward proxy.** `aiohttp.ClientSession()`
  defaulted to `trust_env=False`, so a node whose only outbound path
  is an HTTP(S) forward proxy (e.g. a corporate Squid array with no
  direct egress) could not dial any Link seed or peer at all — every
  outbound request was silently dropped by the firewall before this
  fix, with nothing pointing at the cause. Both production
  `ClientSession` construction sites (the Link sync loop and
  linked-file fetches) now set `trust_env=True`, so the standard
  `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` environment variables work as
  expected. See the README's "Running a node" section for how to set
  this up.
- **SSH self-enrollment restored to the Profile screen.** A
  password-only, self-registered account had no way to add or replace
  its own SSH public key — that capability existed and worked from a
  SysOp's own user-management screen, but was never wired into an
  ordinary caller's own `[P]rofile` screen, so gaining SSH key-based
  login required asking a SysOp to do it on the account's behalf. New
  `SSH public [k]ey` field on `[P]rofile` closes that gap.
- **Unicode decorative-style preference is now revisitable.** The
  Unicode/plain-ASCII breadcrumb-and-punctuation style preference
  (v5.0.0) was only ever set from a one-time post-login confirmation
  prompt; once answered, there was no way to deliberately change it
  again. New `[U]nicode style` field on `[P]rofile`.
- **A misleading "asyncssh is not installed" message is fixed.** SSH
  startup wrapped the entire `from netbbs.net.ssh import SSHServer`
  import in a single broad `except ImportError`, so any import-time
  failure inside that module — not just asyncssh actually being
  absent — was misreported as "not installed" with the real cause
  silently discarded. Observed on a node where `asyncssh` was
  correctly installed but the warning still appeared. The presence
  check is now isolated to `import asyncssh` alone; any other import
  failure in `netbbs.net.ssh` now propagates with its real traceback
  instead of being swallowed.

## Upgrade notes

- No database migration in this release — upgrade is install-and-restart.
- Existing accounts see no behavior change beyond the two new
  `[P]rofile` fields; current preference values are unaffected.
- A node relying on a forward proxy for Link should set
  `HTTP_PROXY`/`HTTPS_PROXY` in its service environment before
  restarting on this version.

## Validation

- The complete pytest suite passes.
- A wheel and source distribution build successfully.
- The wheel installs into a clean virtual environment.
- `python -m netbbs --version` reports v5.0.1 and the current schema.
- Every fix has a regression test confirmed to fail against the
  pre-fix code (`tests/test_main_lifecycle.py::
  test_link_sync_session_honors_forward_proxy_env_vars`,
  `tests/test_login_flow_fullscreen_editor.py`'s new profile tests,
  `tests/test_main_lifecycle.py::
  test_ssh_import_failure_other_than_missing_asyncssh_propagates`).
