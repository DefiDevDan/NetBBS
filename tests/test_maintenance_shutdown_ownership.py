"""Focused regressions for issue #107's shutdown-maintenance ownership race."""

from __future__ import annotations

import asyncio

from netbbs.net.maintenance import MaintenanceMode


async def _owned_gate(mode: MaintenanceMode, started: asyncio.Event) -> None:
    mode.activate()
    started.set()
    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        mode.deactivate()
        raise


def test_cancelled_old_shutdown_cannot_reopen_gate_owned_by_replacement():
    async def scenario() -> None:
        mode = MaintenanceMode()
        old_started = asyncio.Event()
        new_started = asyncio.Event()

        old = asyncio.create_task(_owned_gate(mode, old_started))
        await old_started.wait()
        assert mode.is_active()

        new = asyncio.create_task(_owned_gate(mode, new_started))
        await new_started.wait()
        assert mode.is_active()

        old.cancel()
        await asyncio.gather(old, return_exceptions=True)
        assert mode.is_active(), "stale shutdown cleanup reopened admission owned by the replacement"

        new.cancel()
        await asyncio.gather(new, return_exceptions=True)
        assert not mode.is_active()

    asyncio.run(scenario())


def test_external_cancel_controller_can_release_gate_after_owner_cancel_requested():
    async def scenario() -> None:
        mode = MaintenanceMode()
        started = asyncio.Event()

        owner = asyncio.create_task(_owned_gate(mode, started))
        await started.wait()
        assert mode.is_active()

        # Mirrors the SysOp cancel path: SequenceScheduler.cancel() first
        # requests cancellation of the shutdown task, then the admin task
        # explicitly reopens admission without waiting for the shutdown
        # task's CancelledError handler to run.
        owner.cancel()
        mode.deactivate()
        assert not mode.is_active()

        await asyncio.gather(owner, return_exceptions=True)
        assert not mode.is_active()

    asyncio.run(scenario())
