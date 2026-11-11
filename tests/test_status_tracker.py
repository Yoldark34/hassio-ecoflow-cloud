"""StatusTracker: how silence and explicit statuses turn into online / assume_offline / offline."""

from __future__ import annotations

from datetime import timedelta

from freezegun import freeze_time

from custom_components.ecoflow_cloud.devices.status_tracker import OnlineStatus, StatusTracker


def test_unknown_start_is_offline():
    assert StatusTracker(300).status is OnlineStatus.OFFLINE


def test_initial_status_from_device_list():
    assert StatusTracker(300, initial_status=1).status is OnlineStatus.ONLINE
    assert StatusTracker(300, initial_status=0).status is OnlineStatus.OFFLINE


def test_silence_goes_assume_offline_then_offline():
    with freeze_time("2026-11-11 08:00:00") as clock:
        tracker = StatusTracker(300)
        tracker.on_data_received()
        assert tracker.status is OnlineStatus.ONLINE
        clock.tick(timedelta(seconds=301))
        assert tracker.status is OnlineStatus.ASSUME_OFFLINE
        assert tracker.wants_status_poll
        clock.tick(timedelta(seconds=600))
        assert tracker.status is OnlineStatus.OFFLINE


def test_explicit_offline_wins_until_data_arrives():
    tracker = StatusTracker(300)
    tracker.on_data_received()
    tracker.on_explicit_status(False)
    assert tracker.is_offline
    tracker.on_data_received()
    assert tracker.is_online
