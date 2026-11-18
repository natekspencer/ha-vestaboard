"""Tests for the Vestaboard coordinator."""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import ClientConnectorError, ClientResponseError, ServerDisconnectedError
import pytest

from custom_components.vestaboard.const import DOMAIN, SERVICE_MESSAGE
from homeassistant.const import CONF_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
import homeassistant.util.dt as dt_util

from . import MockConfigEntry


def _refused() -> ClientConnectorError:
    """Return the error aiohttp raises when the board refuses a connection."""
    return ClientConnectorError(
        MagicMock(host="10.10.20.50", port=7000, ssl=None),
        ConnectionRefusedError(111, "Connect call failed"),
    )


@pytest.fixture(autouse=True)
def no_retry_delay() -> Generator[None]:
    """Retry writes without waiting."""
    with patch("custom_components.vestaboard.coordinator.WRITE_RETRY_DELAYS", (0,)):
        yield


async def _send(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Send a message to the board through the message service."""
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_MESSAGE,
        {CONF_DEVICE_ID: [device.id], "message": "HELLO"},
        blocking=True,
    )


async def test_write_retried_after_refused_connection(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test a write goes through once the board takes connections again."""
    coordinator = init_integration.runtime_data
    with patch.object(
        coordinator.vestaboard,
        "write_message",
        AsyncMock(side_effect=[_refused(), True]),
    ) as mock_write:
        await _send(hass, init_integration)

    assert mock_write.await_count == 2
    assert "HELLO" in coordinator.message


async def test_write_gives_up_after_one_retry(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test a board that keeps refusing raises a clear error."""
    coordinator = init_integration.runtime_data
    with (
        patch.object(
            coordinator.vestaboard,
            "write_message",
            AsyncMock(side_effect=_refused()),
        ) as mock_write,
        pytest.raises(HomeAssistantError, match="Couldn't connect to Vestaboard"),
    ):
        await _send(hass, init_integration)

    assert mock_write.await_count == 2


async def test_write_not_retried_once_sent(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test errors after connecting aren't retried, since the board may have the message."""
    coordinator = init_integration.runtime_data
    with (
        patch.object(
            coordinator.vestaboard,
            "write_message",
            AsyncMock(side_effect=ServerDisconnectedError()),
        ) as mock_write,
        pytest.raises(HomeAssistantError, match="Couldn't write message"),
    ):
        await _send(hass, init_integration)

    assert mock_write.await_count == 1


async def test_write_timeout_raises_clear_error(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test a write that times out raises a clear error."""
    coordinator = init_integration.runtime_data
    with (
        patch.object(
            coordinator.vestaboard,
            "write_message",
            AsyncMock(side_effect=TimeoutError()),
        ),
        pytest.raises(HomeAssistantError, match="Couldn't write message"),
    ):
        await _send(hass, init_integration)


async def test_refresh_during_revert_keeps_persistent_message(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test a refresh while a revert is retrying doesn't save the temporary message."""
    coordinator = init_integration.runtime_data
    board = coordinator.vestaboard
    rows, columns = len(board.data), len(board.data[0])
    persistent = [[1] * columns for _ in range(rows)]
    temporary = [[2] * columns for _ in range(rows)]

    await coordinator.async_write_message({"characters": persistent})
    await coordinator.async_write_message(
        {"characters": temporary}, dt_util.now() + timedelta(minutes=5)
    )

    write = board.write_message
    refreshed = False

    async def refuse_once_after_refresh(json, **kwargs):
        nonlocal refreshed
        if not refreshed:
            # The board still shows the temporary message while the revert retries
            refreshed = True
            await coordinator.async_refresh()
            raise _refused()
        return await write(json, **kwargs)

    with patch.object(board, "write_message", side_effect=refuse_once_after_refresh):
        await coordinator.async_clear_temporary_message()

    assert refreshed
    assert coordinator.persistent_message == persistent
    assert board.data == persistent


async def _alert(coordinator):
    """Display an alert over a saved message."""
    board = coordinator.vestaboard
    rows, columns = len(board.data), len(board.data[0])
    persistent = [[1] * columns for _ in range(rows)]
    temporary = [[2] * columns for _ in range(rows)]
    expiration = dt_util.now() + timedelta(minutes=5)
    await coordinator.async_write_message({"characters": persistent})
    await coordinator.async_write_message({"characters": temporary}, expiration)
    return persistent, temporary, expiration


def _assert_cleared(coordinator):
    """Check both expired timer and failed-restore bookkeeping are gone."""
    assert coordinator.temporary_message_expiration is None
    assert coordinator._cancel_cb is None
    assert coordinator._restore_after is None
    assert not coordinator._failed_revert_messages
    assert coordinator._revert_attempt == 0


@pytest.mark.parametrize("expired", [False, True], ids=["clear", "expiry"])
@pytest.mark.parametrize("recover", ["clear", "next_alert", "persistent", "external"])
@pytest.mark.parametrize("failure", ["refused", "timeout", "unconfirmed"])
async def test_failed_revert_keeps_persistent_message(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    expired: bool,
    recover: str,
    failure: str,
) -> None:
    """Protect stranded alerts while only the timer retries recovery."""
    coordinator = init_integration.runtime_data
    board = coordinator.vestaboard
    persistent, temporary, expiration = await _alert(coordinator)
    replacement = [[3] * len(temporary[0]) for _ in temporary]
    write = AsyncMock(return_value=False)
    if failure != "unconfirmed":
        write.side_effect = _refused() if failure == "refused" else TimeoutError()

    with patch.object(board, "write_message", write):
        if expired:
            # Timer failures are logged, not raised out of the HA timer job.
            await coordinator._handle_temporary_message_expiration(expiration)
        else:
            # Explicit service calls still report failure to the caller.
            with pytest.raises(HomeAssistantError):
                await coordinator.async_clear_temporary_message()

        assert coordinator.temporary_message_expiration is not None
        assert coordinator._cancel_cb is not None
        assert coordinator._restore_after is None
        assert coordinator._revert_attempt > 0
        assert coordinator._failed_revert_messages == (
            (temporary,) if failure == "refused" else (temporary, persistent)
        )

        with patch.object(
            coordinator,
            "on_persistent_message",
            wraps=coordinator.on_persistent_message,
        ) as persistent_changed:
            # Polling never writes, saves the alert, or resets backoff.
            for _ in range(3):
                await coordinator.async_refresh()
                assert coordinator.persistent_message == persistent
            persistent_changed.assert_not_called()

    assert write.await_count == (2 if failure == "refused" else 1)
    assert coordinator._revert_attempt == 1
    assert board.data == temporary

    if recover == "clear":
        await coordinator.async_clear_temporary_message()
    elif recover == "next_alert":
        await coordinator.async_write_message({"characters": replacement}, expiration)
        await coordinator._handle_temporary_message_expiration(expiration)
    elif recover == "persistent":
        await coordinator.async_write_message({"characters": replacement})
        assert board.data == temporary
        await coordinator._handle_temporary_message_expiration(
            coordinator.temporary_message_expiration
        )
        persistent = replacement
    else:
        # A change from the native app is learned, not overwritten by a retry.
        await board.write_message({"characters": replacement})
        with patch.object(board, "write_message", AsyncMock()) as unexpected_write:
            await coordinator.async_refresh()
        unexpected_write.assert_not_called()
        persistent = replacement

    assert board.data == persistent
    assert coordinator.data == persistent
    assert coordinator.persistent_message == persistent
    _assert_cleared(coordinator)

    # Normal capture works again, including after a plain persistent write.
    external = [[4] * len(temporary[0]) for _ in temporary]
    await board.write_message({"characters": external})
    await coordinator.async_refresh()
    assert coordinator.persistent_message == external


async def test_failed_revert_recovers_on_next_timer(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A successful read does not write; the next timer restores the board."""
    coordinator = init_integration.runtime_data
    persistent, _, expiration = await _alert(coordinator)
    board = coordinator.vestaboard
    with patch.object(board, "write_message", AsyncMock(side_effect=TimeoutError())):
        await coordinator._handle_temporary_message_expiration(expiration)

    # Failed reads do not use up the recovery attempt.
    with patch.object(board, "read_message", AsyncMock(side_effect=TimeoutError())):
        await coordinator.async_refresh()
    assert coordinator._revert_attempt > 0

    with patch.object(board, "write_message", wraps=board.write_message) as write:
        await coordinator.async_refresh()
        write.assert_not_called()
        await coordinator._handle_temporary_message_expiration(
            coordinator.temporary_message_expiration
        )
        await coordinator.async_refresh()
    assert write.await_count == 1
    assert board.data == persistent
    assert coordinator.data == persistent
    _assert_cleared(coordinator)


@pytest.mark.parametrize("during_retry", [False, True])
async def test_unconfirmed_restore_that_reached_board_is_not_replayed(
    hass: HomeAssistant, init_integration: MockConfigEntry, during_retry: bool
) -> None:
    """A read confirms an accepted write even if its acknowledgement was lost."""
    coordinator = init_integration.runtime_data
    persistent, _, expiration = await _alert(coordinator)
    board = coordinator.vestaboard
    original_write = board.write_message

    async def write_then_timeout(json):
        await original_write(json)
        raise TimeoutError

    if during_retry:
        with patch.object(
            board, "write_message", AsyncMock(side_effect=TimeoutError())
        ):
            await coordinator._handle_temporary_message_expiration(expiration)

    with patch.object(board, "write_message", side_effect=write_then_timeout) as write:
        if during_retry:
            await coordinator._handle_temporary_message_expiration(
                coordinator.temporary_message_expiration
            )
        else:
            await coordinator._handle_temporary_message_expiration(expiration)
        await coordinator.async_refresh()
        await coordinator.async_refresh()
    assert write.await_count == 1
    assert board.data == persistent
    assert coordinator.persistent_message == persistent
    _assert_cleared(coordinator)


async def test_external_change_before_recovery_is_not_overwritten(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Reconcile a native-app write before spending the pending retry."""
    coordinator = init_integration.runtime_data
    _, temporary, expiration = await _alert(coordinator)
    board = coordinator.vestaboard
    with patch.object(board, "write_message", AsyncMock(side_effect=TimeoutError())):
        await coordinator._handle_temporary_message_expiration(expiration)
    external = [[4] * len(temporary[0]) for _ in temporary]
    await board.write_message({"characters": external})
    with patch.object(board, "write_message", AsyncMock()) as write:
        await coordinator.async_refresh()
    write.assert_not_called()
    assert coordinator.persistent_message == external
    _assert_cleared(coordinator)


async def test_clear_and_queued_expiration_write_only_once(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """An expiration already waiting on the lock does nothing after clear."""
    coordinator = init_integration.runtime_data
    persistent, _, expiration = await _alert(coordinator)
    board = coordinator.vestaboard
    with patch.object(board, "write_message", wraps=board.write_message) as write:
        async with coordinator._temporary_message_lock:
            clear = asyncio.create_task(coordinator.async_clear_temporary_message())
            expiry = asyncio.create_task(
                coordinator._handle_temporary_message_expiration(expiration)
            )
            await asyncio.sleep(0)
        await asyncio.gather(clear, expiry)
    assert write.await_count == 1
    assert board.data == persistent
    _assert_cleared(coordinator)


@pytest.mark.parametrize("unconfirmed_replacement", [False, True])
async def test_clear_after_expiration_leaves_pending_restore_to_callback(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    unconfirmed_replacement: bool,
) -> None:
    """Clear must not discard the previous temporary message at expiration."""
    coordinator = init_integration.runtime_data
    _, temporary, expiration = await _alert(coordinator)
    parent = [[3] * len(temporary[0]) for _ in temporary]
    parent_expiration = expiration + timedelta(minutes=5)
    coordinator._restore_after = (parent, parent_expiration)
    board = coordinator.vestaboard
    if unconfirmed_replacement:
        with (
            patch.object(board, "write_message", AsyncMock(side_effect=TimeoutError())),
            pytest.raises(HomeAssistantError),
        ):
            await coordinator.async_write_message(
                {"characters": parent},
                expiration,
                restore_after=(parent, parent_expiration),
            )
    with (
        patch("homeassistant.util.dt.now", return_value=expiration),
        patch.object(board, "write_message", wraps=board.write_message) as write,
    ):
        async with coordinator._temporary_message_lock:
            clear = asyncio.create_task(coordinator.async_clear_temporary_message())
            expiry = asyncio.create_task(
                coordinator._handle_temporary_message_expiration(expiration)
            )
            await asyncio.sleep(0)
        await asyncio.gather(clear, expiry)
    assert write.await_count == 1
    assert board.data == parent
    assert coordinator.temporary_message_expiration == parent_expiration
    assert coordinator._restore_after is None
    await coordinator.async_clear_temporary_message()


async def test_read_started_before_new_write_cannot_capture_old_alert(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A stale read cannot undo a newer persistent write or re-arm recovery."""
    coordinator = init_integration.runtime_data
    _, temporary, expiration = await _alert(coordinator)
    board = coordinator.vestaboard
    with patch.object(board, "write_message", AsyncMock(side_effect=TimeoutError())):
        await coordinator._handle_temporary_message_expiration(expiration)
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed_read():
        started.set()
        await release.wait()
        return temporary

    external = [[4] * len(temporary[0]) for _ in temporary]
    with patch.object(board, "read_message", side_effect=delayed_read):
        refresh = asyncio.create_task(coordinator.async_refresh())
        await started.wait()
        await coordinator.async_write_message({"characters": external})
        await coordinator._handle_temporary_message_expiration(
            coordinator.temporary_message_expiration
        )
        release.set()
        await refresh
    assert coordinator.persistent_message == external
    assert coordinator.data == external
    _assert_cleared(coordinator)


async def test_read_waiting_behind_clear_cannot_capture_old_alert(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Recheck freshness after a fair lock acquisition yields to queued clear."""
    coordinator = init_integration.runtime_data
    persistent, temporary, _ = await _alert(coordinator)
    lock = coordinator._temporary_message_lock
    await lock.acquire()
    clear = asyncio.create_task(coordinator.async_clear_temporary_message())
    await asyncio.sleep(0)  # Clear is now queued on the real asyncio lock.
    lock.release()  # Wake clear without running it yet.
    assert not lock.locked()
    revision = coordinator._write_revision
    try:
        # The virtual board read does not suspend. Poll passes its initial
        # checks, then fair acquisition puts it behind the awakened clear.
        data = await coordinator._async_update_data()
    finally:
        await clear
    assert coordinator._write_revision > revision
    assert coordinator.vestaboard.data == persistent
    assert coordinator.persistent_message == persistent
    assert coordinator.data == persistent
    assert data == persistent
    assert data != temporary
    _assert_cleared(coordinator)


async def test_failed_expiration_rearms_sensor_and_array_expiration(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A failed restore is advertised with its future retry expiration."""
    from custom_components.vestaboard.coordinator import VestaboardArrayCoordinator

    coordinator = init_integration.runtime_data
    _, _, expiration = await _alert(coordinator)
    assert hass.states.get("binary_sensor.test_board_temporary_message").state == "on"
    with patch.object(
        coordinator.vestaboard, "write_message", AsyncMock(side_effect=TimeoutError())
    ):
        await coordinator._handle_temporary_message_expiration(expiration)
    assert hass.states.get("binary_sensor.test_board_temporary_message").state == "on"
    assert (
        hass.states.get("sensor.test_board_temporary_message_expiration").state
        != "unknown"
    )
    # The array reports the retry deadline, not the expired alert deadline.
    array = MagicMock()
    array.members.return_value = [[coordinator]]
    assert (
        VestaboardArrayCoordinator.temporary_message_expiration.fget(array)
        == coordinator.temporary_message_expiration
    )
    await coordinator.async_clear_temporary_message()


async def test_failed_parent_restore_also_uses_timer_recovery(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Failure restoring both a previous alert and the persistent message is contained."""
    coordinator = init_integration.runtime_data
    persistent, temporary, expiration = await _alert(coordinator)
    parent = [[3] * len(temporary[0]) for _ in temporary]
    coordinator._restore_after = (parent, expiration + timedelta(minutes=5))
    with patch.object(
        coordinator.vestaboard, "write_message", AsyncMock(side_effect=TimeoutError())
    ) as write:
        await coordinator._handle_temporary_message_expiration(expiration)
        assert write.await_count == 2
        assert coordinator.temporary_message_expiration is not None
        assert coordinator._restore_after is None
        assert coordinator._cancel_cb is not None
    await coordinator.async_refresh()
    await coordinator._handle_temporary_message_expiration(
        coordinator.temporary_message_expiration
    )
    assert coordinator.vestaboard.data == persistent
    _assert_cleared(coordinator)


async def test_read_started_during_revert_cannot_capture_old_alert(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A read spanning the end of a restore cannot re-save the alert after unlock."""
    coordinator = init_integration.runtime_data
    persistent, temporary, _ = await _alert(coordinator)
    board = coordinator.vestaboard
    write_started, release_write = asyncio.Event(), asyncio.Event()
    read_started, release_read = asyncio.Event(), asyncio.Event()
    original_write = board.write_message

    async def delayed_write(json):
        write_started.set()
        await release_write.wait()
        return await original_write(json)

    async def delayed_read():
        read_started.set()
        await release_read.wait()
        return temporary

    with (
        patch.object(board, "write_message", side_effect=delayed_write),
        patch.object(board, "read_message", side_effect=delayed_read),
    ):
        clear = asyncio.create_task(coordinator.async_clear_temporary_message())
        await write_started.wait()
        refresh = asyncio.create_task(coordinator.async_refresh())
        await read_started.wait()
        release_write.set()
        await clear
        release_read.set()
        await refresh
    assert coordinator.persistent_message == persistent
    assert coordinator.data == persistent
    _assert_cleared(coordinator)


@pytest.mark.parametrize("parent_restore", [True, False], ids=["parent", "new_alert"])
async def test_unconfirmed_alert_during_recovery_is_not_saved_as_persistent(
    hass: HomeAssistant, init_integration: MockConfigEntry, parent_restore: bool
) -> None:
    """An unacknowledged alert write is still known temporary content, not an app edit."""
    coordinator = init_integration.runtime_data
    persistent, temporary, expiration = await _alert(coordinator)
    board = coordinator.vestaboard
    other_alert = [[3] * len(temporary[0]) for _ in temporary]
    original_write = board.write_message

    async def accept_alert_but_timeout(json):
        if json["characters"] == other_alert:
            await original_write(json)
        raise TimeoutError

    if parent_restore:
        coordinator._restore_after = (other_alert, expiration + timedelta(minutes=5))
        with patch.object(board, "write_message", side_effect=accept_alert_but_timeout):
            await coordinator._handle_temporary_message_expiration(expiration)
    else:
        with patch.object(
            board, "write_message", AsyncMock(side_effect=TimeoutError())
        ):
            await coordinator._handle_temporary_message_expiration(expiration)
        with (
            patch.object(board, "write_message", side_effect=accept_alert_but_timeout),
            pytest.raises(HomeAssistantError),
        ):
            await coordinator.async_write_message(
                {"characters": other_alert}, expiration + timedelta(minutes=5)
            )
    assert board.data == other_alert
    await coordinator.async_refresh()
    assert coordinator.persistent_message == persistent
    await coordinator._handle_temporary_message_expiration(
        coordinator.temporary_message_expiration
    )
    assert board.data == persistent
    _assert_cleared(coordinator)


@pytest.mark.parametrize("accepted", [False, True], ids=["not_applied", "applied"])
@pytest.mark.parametrize("failure", ["timeout", "unconfirmed"])
async def test_unconfirmed_alert_before_recovery_preserves_both_possible_displays(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    accepted: bool,
    failure: str,
) -> None:
    """Neither the old alert nor an unconfirmed replacement may become persistent."""
    coordinator = init_integration.runtime_data
    persistent, temporary, expiration = await _alert(coordinator)
    board = coordinator.vestaboard
    replacement = [[3] * len(temporary[0]) for _ in temporary]
    original_write = board.write_message

    async def unconfirmed_alert(json):
        if accepted:
            await original_write(json)
        if failure == "timeout":
            raise TimeoutError
        return False

    # No failed-revert state exists yet. B may replace A physically without
    # updating the cached display or replacing A's existing expiration timer.
    with (
        patch.object(board, "write_message", side_effect=unconfirmed_alert),
        pytest.raises(HomeAssistantError),
    ):
        await coordinator.async_write_message(
            {"characters": replacement}, expiration + timedelta(minutes=5)
        )
    assert coordinator.data == temporary
    assert board.data == (replacement if accepted else temporary)

    # Do not poll between B's unconfirmed write and A's failed expiration restore.
    with patch.object(board, "write_message", AsyncMock(side_effect=TimeoutError())):
        await coordinator._handle_temporary_message_expiration(expiration)
        with patch.object(
            coordinator,
            "on_persistent_message",
            wraps=coordinator.on_persistent_message,
        ) as persistent_changed:
            await coordinator.async_refresh()
            assert coordinator.persistent_message == persistent
            persistent_changed.assert_not_called()

    await coordinator.async_clear_temporary_message()
    assert board.data == persistent
    _assert_cleared(coordinator)


async def test_revert_backoff_and_poll_narrowing(hass, init_integration):
    """Retry only on deadlines, narrowing uncertain content on fresh reads."""
    coordinator = init_integration.runtime_data
    _, temporary, expiration = await _alert(coordinator)
    other = [[3] * len(temporary[0]) for _ in temporary]
    coordinator._failed_revert_messages = (temporary, other)
    board = coordinator.vestaboard
    now = dt_util.now()
    with (
        patch("homeassistant.util.dt.now", return_value=now) as clock,
        patch.object(
            board, "write_message", AsyncMock(side_effect=TimeoutError())
        ) as write,
    ):
        for attempt, seconds in enumerate((30, 60, 120, 300, 300), 1):
            await coordinator._handle_temporary_message_expiration(expiration)
            expiration = coordinator.temporary_message_expiration
            assert expiration == now + timedelta(seconds=seconds)
            assert coordinator._revert_attempt == attempt
            await coordinator.async_refresh()
            assert coordinator._failed_revert_messages == (temporary,)
            assert write.await_count == attempt
            now = expiration
            clock.return_value = now
    await coordinator.async_clear_temporary_message()
    _assert_cleared(coordinator)


@pytest.mark.parametrize(
    "error", [RuntimeError("executor failed"), asyncio.CancelledError()]
)
async def test_revert_retains_tracking_on_unexpected_error(
    hass, init_integration, error
):
    """Cancellation propagates but leaves an armed recovery timer."""
    coordinator = init_integration.runtime_data
    persistent, temporary, _ = await _alert(coordinator)
    with (
        patch.object(
            coordinator.vestaboard, "write_message", AsyncMock(side_effect=error)
        ),
        pytest.raises(type(error)),
    ):
        await coordinator.async_clear_temporary_message()
    assert coordinator._failed_revert_messages == (temporary, persistent)
    assert coordinator._cancel_cb is not None
    await coordinator.async_refresh()
    assert coordinator.persistent_message == persistent
    await coordinator.async_clear_temporary_message()
    _assert_cleared(coordinator)


async def test_persistent_write_preserves_queued_parent_restore(hass, init_integration):
    """A persistent write between deadline and callback must not discard the parent."""
    coordinator = init_integration.runtime_data
    _, temporary, expiration = await _alert(coordinator)
    parent = [[3] * len(temporary[0]) for _ in temporary]
    replacement = [[4] * len(temporary[0]) for _ in temporary]
    parent_expiration = expiration + timedelta(minutes=5)
    coordinator._restore_after = (parent, parent_expiration)
    with patch("homeassistant.util.dt.now", return_value=expiration):
        await coordinator.async_write_message({"characters": replacement})
        assert coordinator.vestaboard.data == replacement
        await coordinator._handle_temporary_message_expiration(expiration)
    assert coordinator.vestaboard.data == parent
    assert coordinator.temporary_message_expiration == parent_expiration
    await coordinator.async_clear_temporary_message()
    assert coordinator.vestaboard.data == replacement
    _assert_cleared(coordinator)


async def test_stale_initial_read_does_not_publish_none(hass, init_integration):
    """A stale first read is a failed update, not successful uninitialized data."""
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coordinator = init_integration.runtime_data
    coordinator.data = None
    coordinator._write_in_progress = True
    with pytest.raises(UpdateFailed, match="superseded"):
        await coordinator._async_update_data()
    coordinator._write_in_progress = False


async def test_retry_callback_runs_from_ha_timer(hass, init_integration):
    """The actual HA timer recovers without any successful poll initiating writes."""
    try:
        from pytest_homeassistant.common import async_fire_time_changed
    except ImportError:  # Home Assistant < 2026.11
        from pytest_homeassistant_custom_component.common import async_fire_time_changed

    coordinator = init_integration.runtime_data
    persistent, _, expiration = await _alert(coordinator)
    with patch.object(
        coordinator.vestaboard, "write_message", AsyncMock(side_effect=TimeoutError())
    ):
        await coordinator._handle_temporary_message_expiration(expiration)
    deadline = coordinator.temporary_message_expiration
    async_fire_time_changed(hass, deadline + timedelta(seconds=1))
    await hass.async_block_till_done()
    assert coordinator.vestaboard.data == persistent
    _assert_cleared(coordinator)


async def test_persistent_write_notifies_once(hass, init_integration):
    """State is cleared before publishing the persistent write's one update."""
    coordinator = init_integration.runtime_data
    with patch.object(
        coordinator, "async_update_listeners", wraps=coordinator.async_update_listeners
    ) as notify:
        await coordinator.async_write_message(
            {"characters": [[1] * 22 for _ in range(6)]}
        )
    assert notify.call_count == 1


async def test_queued_persistent_update_after_lost_restore_ack(hass, init_integration):
    """An old successful restore must not overwrite a newly queued persistent target."""
    coordinator = init_integration.runtime_data
    _, temporary, expiration = await _alert(coordinator)
    board = coordinator.vestaboard
    original_write = board.write_message

    async def accepted_without_ack(payload):
        await original_write(payload)
        raise TimeoutError

    with patch.object(board, "write_message", side_effect=accepted_without_ack):
        await coordinator._handle_temporary_message_expiration(expiration)
    replacement = [[4] * len(temporary[0]) for _ in temporary]
    await coordinator.async_write_message({"characters": replacement})
    await coordinator.async_refresh()
    assert coordinator.persistent_message == replacement
    await coordinator._handle_temporary_message_expiration(
        coordinator.temporary_message_expiration
    )
    assert board.data == replacement
    _assert_cleared(coordinator)


@pytest.mark.parametrize("active", [False, True])
async def test_unsent_alert_does_not_create_recovery(hass, init_integration, active):
    """A connect refusal preserves exactly the previous timer and tracking."""
    c = init_integration.runtime_data
    if active:
        await _alert(c)
    before = (c.temporary_message_expiration, c._cancel_cb, c._failed_revert_messages)
    with (
        patch.object(c.vestaboard, "write_message", AsyncMock(side_effect=_refused())),
        pytest.raises(HomeAssistantError),
    ):
        await c.async_write_message(
            {"characters": [[5] * len(c.data[0]) for _ in c.data]},
            dt_util.now() + timedelta(minutes=10),
        )
    assert (
        c.temporary_message_expiration,
        c._cancel_cb,
        c._failed_revert_messages,
    ) == before
    assert c._revert_attempt == 0
    if active:
        await c.async_clear_temporary_message()


@pytest.mark.parametrize("error", [TimeoutError(), asyncio.CancelledError()])
async def test_uncertain_new_alert_keeps_requested_deadline(
    hass, init_integration, error
):
    """Uncertainty, including cancellation, arms the original alert lifetime."""
    c = init_integration.runtime_data
    persistent = c.persistent_message
    alert = [[5] * len(c.data[0]) for _ in c.data]
    deadline = dt_util.now() + timedelta(minutes=10)
    with (
        patch.object(c.vestaboard, "write_message", AsyncMock(side_effect=error)),
        pytest.raises((HomeAssistantError, asyncio.CancelledError)),
    ):
        await c.async_write_message({"characters": alert}, deadline)
    assert c.temporary_message_expiration == deadline
    assert c._cancel_cb is not None
    assert c._revert_attempt == 0
    assert c._failed_revert_messages == (alert,)
    await c._handle_temporary_message_expiration(deadline)
    assert c.vestaboard.data == persistent
    _assert_cleared(c)


async def test_poll_preserves_expired_parent_handoff(hass, init_integration):
    """Settling an uncertain child must not cancel the queued parent."""
    c = init_integration.runtime_data
    persistent, child, deadline = await _alert(c)
    parent = [[3] * len(child[0]) for _ in child]
    c._restore_after = (parent, deadline + timedelta(minutes=5))
    c._failed_revert_messages = (child,)
    await c.vestaboard.write_message({"characters": persistent})
    with patch("homeassistant.util.dt.now", return_value=deadline):
        await c.async_refresh()
        assert c._restore_after is not None
        assert c._cancel_cb is not None
        await c._handle_temporary_message_expiration(deadline)
    assert c.vestaboard.data == parent
    await c.async_clear_temporary_message()


async def test_queued_persistent_targets_do_not_accumulate(hass, init_integration):
    """Only a target actually attempted on the wire is uncertain."""
    c = init_integration.runtime_data
    persistent, child, deadline = await _alert(c)
    with patch.object(
        c.vestaboard, "write_message", AsyncMock(side_effect=TimeoutError())
    ):
        await c._handle_temporary_message_expiration(deadline)
    for number in range(3, 10):
        await c.async_write_message(
            {"characters": [[number] * len(child[0]) for _ in child]}
        )
    assert c._failed_revert_messages == (child, persistent)
    external = [[4] * len(child[0]) for _ in child]
    await c.vestaboard.write_message({"characters": external})
    await c.async_refresh()
    assert c.persistent_message == external
    _assert_cleared(c)


async def test_render_does_not_block_write_or_publish_stale_state(
    hass, init_integration
):
    """A write during slow poll rendering wins both image and persistent state."""
    import threading

    c = init_integration.runtime_data
    persistent, child, _ = await _alert(c)
    started, release = threading.Event(), threading.Event()
    prepare = c._prepare_data

    def delayed(data):
        if data == child:
            started.set()
            assert release.wait(10)
        return prepare(data)

    with patch.object(c, "_prepare_data", side_effect=delayed):
        poll = asyncio.create_task(c.async_refresh())
        try:
            assert await asyncio.to_thread(started.wait, 10)
            await asyncio.wait_for(c.async_clear_temporary_message(), 5)
            message, image = c.message, c.image
        finally:
            release.set()
            await poll
    assert c.data == c.persistent_message == persistent
    assert (c.message, c.image) == (message, image)


async def test_read_behind_noop_lock_is_not_discarded(hass, init_integration):
    """A lock holder that never writes cannot invalidate the first read."""
    c = init_integration.runtime_data
    c.data = None
    async with c._temporary_message_lock:
        poll = asyncio.create_task(c._async_update_data())
        await asyncio.sleep(0)
    assert await poll == c.vestaboard.data


async def test_cancelled_expired_persistent_write_rearms_recovery(
    hass, init_integration
):
    """A cancelled write after the alert expires does not strand it forever."""
    c = init_integration.runtime_data
    _, child, deadline = await _alert(c)
    replacement = [[4] * len(child[0]) for _ in child]
    with (
        patch("homeassistant.util.dt.now", return_value=deadline),
        patch.object(
            c.vestaboard,
            "write_message",
            AsyncMock(side_effect=asyncio.CancelledError()),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await c.async_write_message({"characters": replacement})
    assert c._cancel_cb is not None
    assert c.temporary_message_expiration is not None
    await c._handle_temporary_message_expiration(c.temporary_message_expiration)
    assert c.vestaboard.data == replacement
    _assert_cleared(c)


async def test_successive_lost_revert_acks_preserve_actual_wire_targets(
    hass, init_integration
):
    """Do not mistake an earlier possibly delivered restore for an app edit."""
    c = init_integration.runtime_data
    persistent, child, deadline = await _alert(c)
    original = c.vestaboard.write_message

    async def accepted(json):
        await original(json)
        raise TimeoutError

    with patch.object(c.vestaboard, "write_message", side_effect=accepted):
        await c._handle_temporary_message_expiration(deadline)
    replacement = [[4] * len(child[0]) for _ in child]
    await c.async_write_message({"characters": replacement})
    with patch.object(
        c.vestaboard, "write_message", AsyncMock(side_effect=TimeoutError())
    ):
        await c._handle_temporary_message_expiration(c.temporary_message_expiration)
    assert c.vestaboard.data == persistent
    await c.async_refresh()
    assert c.persistent_message == replacement
    await c.async_clear_temporary_message()
    assert c.vestaboard.data == replacement


async def test_cancel_during_connect_backoff_does_not_track_unsent_alert(
    hass, init_integration
):
    """A cancelled connection retry never admitted the alert."""
    c = init_integration.runtime_data
    with (
        patch("custom_components.vestaboard.coordinator.WRITE_RETRY_DELAYS", (60,)),
        patch.object(
            c.vestaboard, "write_message", AsyncMock(side_effect=_refused())
        ) as write,
    ):
        task = asyncio.create_task(
            c.async_write_message(
                {"characters": c.data}, dt_util.now() + timedelta(minutes=5)
            )
        )
        await asyncio.sleep(0)
        assert write.await_count == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    _assert_cleared(c)


@pytest.mark.parametrize(
    "status,rejected",
    [
        (400, True),
        (401, True),
        (403, True),
        (404, True),
        (413, True),
        (422, True),
        (500, False),
    ],
)
async def test_http_refusal_vs_unknown_delivery(
    hass, init_integration, status, rejected
):
    """Explicit request refusal differs from a server failure after admission."""
    c = init_integration.runtime_data
    alert = [[3] * len(c.data[0]) for _ in c.data]
    error = ClientResponseError(
        MagicMock(real_url="http://board/message"), (), status=status
    )
    deadline = dt_util.now() + timedelta(minutes=5)
    with (
        patch.object(c.vestaboard, "write_message", AsyncMock(side_effect=error)),
        pytest.raises(HomeAssistantError),
    ):
        await c.async_write_message({"characters": alert}, deadline)
    if rejected:
        _assert_cleared(c)
    else:
        assert c.temporary_message_expiration == deadline
        assert c._failed_revert_messages == (alert,)
        await c.async_clear_temporary_message()


async def test_uncertain_identify_write_retains_requested_parent(
    hass, init_integration
):
    """A possibly delivered short overlay still restores the active parent."""
    c = init_integration.runtime_data
    _, parent, parent_deadline = await _alert(c)
    deadline = dt_util.now() + timedelta(seconds=30)
    overlay = [[5] * len(parent[0]) for _ in parent]
    with (
        patch.object(
            c.vestaboard, "write_message", AsyncMock(side_effect=TimeoutError())
        ),
        pytest.raises(HomeAssistantError),
    ):
        await c.async_write_message(
            {"characters": overlay}, deadline, restore_after=(parent, parent_deadline)
        )
    assert c._restore_after == (parent, parent_deadline)
    await c._handle_temporary_message_expiration(deadline)
    assert c.vestaboard.data == parent
    assert c.temporary_message_expiration == parent_deadline
    await c.async_clear_temporary_message()


@pytest.mark.parametrize("expired_parent", [False, True])
async def test_immediate_persistent_write_preserves_supplied_settings(
    hass, init_integration, expired_parent
):
    """The immediate service path forwards caller settings, not restore defaults."""
    c = init_integration.runtime_data
    now = dt_util.now()
    rows = [[4] * len(c.data[0]) for _ in c.data]
    if expired_parent:
        _, child, now = await _alert(c)
        c._restore_after = (child, now + timedelta(minutes=5))
    payload = {
        "characters": rows,
        "strategy": "random",
        "step_interval_ms": 123,
        "step_size": 2,
    }
    with (
        patch("homeassistant.util.dt.now", return_value=now),
        patch.object(
            c.vestaboard, "write_message", wraps=c.vestaboard.write_message
        ) as write,
    ):
        await c.async_write_message(payload)
    write.assert_awaited_once_with(payload)
    assert c.vestaboard.data == rows
    if expired_parent:
        await c._handle_temporary_message_expiration(now)
    await c.async_clear_temporary_message()


@pytest.mark.parametrize("parent_expires_before_retry", [False, True])
async def test_cancelled_queued_parent_connect_retry_rearms_timer(
    hass, init_integration, parent_expires_before_retry
):
    """Cancellation before admission preserves the parent and real timer recovery."""
    try:
        from pytest_homeassistant.common import async_fire_time_changed
    except ImportError:  # Home Assistant < 2026.11
        from pytest_homeassistant_custom_component.common import async_fire_time_changed

    c = init_integration.runtime_data
    persistent, child, deadline = await _alert(c)
    parent = [[3] * len(child[0]) for _ in child]
    parent_deadline = deadline + timedelta(
        seconds=10 if parent_expires_before_retry else 300
    )
    c._restore_after = (parent, parent_deadline)
    with (
        patch("homeassistant.util.dt.now", return_value=deadline),
        patch("custom_components.vestaboard.coordinator.WRITE_RETRY_DELAYS", (60,)),
        patch.object(
            c.vestaboard, "write_message", AsyncMock(side_effect=_refused())
        ) as write,
    ):
        task = asyncio.create_task(c._handle_temporary_message_expiration(deadline))
        await asyncio.sleep(0)
        assert write.await_count == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    retry = c.temporary_message_expiration
    assert retry > deadline
    assert c._restore_after == (parent, parent_deadline)
    assert c._cancel_cb is not None
    assert not c._failed_revert_messages  # The parent was never sent.
    assert c.vestaboard.data == child
    await c.async_refresh()  # Polling must not steal the timer's handoff.
    async_fire_time_changed(hass, retry + timedelta(seconds=1))
    await hass.async_block_till_done()
    if parent_expires_before_retry:
        assert c.vestaboard.data == persistent
        _assert_cleared(c)
    else:
        assert c.vestaboard.data == parent
        assert c.temporary_message_expiration == parent_deadline
        assert c._restore_after is None
        async_fire_time_changed(hass, parent_deadline + timedelta(seconds=1))
        await hass.async_block_till_done()
        assert c.vestaboard.data == persistent
        _assert_cleared(c)


@pytest.mark.parametrize("restore", ["clear", "timer"])
async def test_deferred_restore_uses_default_transition_settings(
    hass, init_integration, restore
):
    """Caller settings belong to immediate writes, not later automatic restores."""
    c = init_integration.runtime_data
    defaults = {"strategy": "column", "step_interval_ms": 321}
    hass.config_entries.async_update_entry(
        init_integration, options={**init_integration.options, "strategy": defaults}
    )
    persistent, _, deadline = await _alert(c)
    with patch.object(
        c.vestaboard, "write_message", wraps=c.vestaboard.write_message
    ) as write:
        if restore == "clear":
            await c.async_clear_temporary_message()
        else:
            await c._handle_temporary_message_expiration(deadline)
    write.assert_awaited_once_with({"characters": persistent, **defaults})
    _assert_cleared(c)
