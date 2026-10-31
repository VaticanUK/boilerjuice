"""Rebuilding consumption history from the recorder's tank volumes."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from custom_components.boilerjuice import consumption
from custom_components.boilerjuice.const import DOMAIN
from custom_components.boilerjuice.tank import TankTracker
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .helpers import TANK_ID, coordinator_of, setup_account, tracker_of

LONDON = ZoneInfo("Europe/London")


def at(month: int, day: int, hour: int = 0) -> datetime:
    return datetime(2026, month, day, hour, tzinfo=LONDON)


def midnight(date_str: str) -> datetime:
    return datetime.fromisoformat(date_str).replace(tzinfo=LONDON)


# --- reconstruction -------------------------------------------------------


def test_each_fall_is_spread_over_the_days_since_the_last() -> None:
    history = consumption.history_from_volumes(
        [(at(7, 1), 1000.0), (at(7, 5), 960.0), (at(7, 6), 950.0)]
    )

    assert consumption.daily_totals(history) == {
        "2026-07-01": 10.0,
        "2026-07-02": 10.0,
        "2026-07-03": 10.0,
        "2026-07-04": 10.0,
        "2026-07-05": 10.0,
    }


def test_a_small_rise_is_noise_not_a_refill() -> None:
    """Stepping back up 10 L must not let the next step down count twice."""
    history = consumption.history_from_volumes(
        [
            (at(7, 1), 1000.0),
            (at(7, 2), 990.0),
            (at(7, 3), 1000.0),
            (at(7, 4), 990.0),
            (at(7, 5), 980.0),
        ]
    )

    assert sum(litres for _, litres in history) == pytest.approx(20.0)


def test_a_refill_starts_a_new_interval() -> None:
    history = consumption.history_from_volumes(
        [
            (at(7, 1), 300.0),
            (at(7, 2), 290.0),
            (at(7, 3), 1290.0),
            (at(7, 5), 1270.0),
        ]
    )

    assert consumption.daily_totals(history) == {
        "2026-07-01": 10.0,
        "2026-07-03": 10.0,
        "2026-07-04": 10.0,
    }


def test_samples_out_of_order_are_sorted_first() -> None:
    history = consumption.history_from_volumes([(at(7, 2), 990.0), (at(7, 1), 1000.0)])

    assert consumption.daily_totals(history) == {"2026-07-01": 10.0}


def test_no_samples_rebuild_nothing() -> None:
    assert consumption.history_from_volumes([]) == []


# --- merging --------------------------------------------------------------


def tracker_with(history: dict[str, float], last_update: datetime) -> TankTracker:
    tracker = TankTracker("123456", midnight=midnight)
    tracker.state.history = [(midnight(day), litres) for day, litres in history.items()]
    tracker.state.last_update = last_update
    tracker.state.total_litres = 500.0
    return tracker


IMPORTED = [(midnight(f"2026-09-{day:02d}"), 4.0) for day in range(25, 31)] + [
    (midnight("2026-10-01"), 4.0),
    (midnight("2026-10-02"), 4.0),
    (midnight("2026-10-03"), 4.0),
]


def test_only_days_before_our_own_history_are_taken() -> None:
    tracker = tracker_with({"2026-10-02": 1.5, "2026-10-03": 3.0}, at(10, 3, 9))

    result = tracker.import_history(IMPORTED, at(10, 31, 12))

    assert result == {
        "days": 7,
        "litres": 28.0,
        "first_day": "2026-09-25",
        "last_day": "2026-10-01",
    }
    totals = consumption.daily_totals(tracker.state.history)
    # Our own partial first day is kept as it was, not topped up.
    assert totals["2026-10-02"] == 1.5
    assert totals["2026-10-01"] == 4.0


def test_importing_twice_adds_nothing() -> None:
    tracker = tracker_with({"2026-10-02": 1.5}, at(10, 3, 9))
    tracker.import_history(IMPORTED, at(10, 31, 12))
    before = list(tracker.state.history)

    result = tracker.import_history(IMPORTED, at(10, 31, 12))

    assert result["days"] == 0
    assert result["first_day"] is None
    assert tracker.state.history == before


def test_days_awaiting_the_next_drop_are_left_alone() -> None:
    """After the last level change, the next drop will spread over them."""
    tracker = tracker_with({}, at(9, 28, 9))

    result = tracker.import_history(IMPORTED, at(10, 31, 12))

    assert result["last_day"] == "2026-09-27"


def test_with_no_history_at_all_every_day_before_today_is_taken() -> None:
    tracker = TankTracker("123456", midnight=midnight)

    result = tracker.import_history(IMPORTED, at(10, 3, 12))

    assert result["last_day"] == "2026-10-02"
    assert tracker.daily_litres == 4.0


def test_the_totals_are_not_restated() -> None:
    tracker = tracker_with({}, at(10, 3, 9))

    tracker.import_history(IMPORTED, at(10, 31, 12))

    assert tracker.total_litres == 500.0


def test_nothing_older_than_the_history_window_is_taken() -> None:
    tracker = tracker_with({}, at(10, 3, 9))
    ancient = [(midnight("2020-01-01"), 4.0)]

    assert tracker.import_history(ancient, at(10, 31, 12))["days"] == 0


# --- the action -----------------------------------------------------------


def recorded(days: int, per_day: float = 5.0) -> list[tuple[datetime, float]]:
    """Return a tank falling `per_day` litres a day, recorded twice a day."""
    start = dt_util.start_of_local_day() - timedelta(days=days)
    return [
        (start + timedelta(hours=12 * n), 2000.0 - per_day * n / 2)
        for n in range(days * 2)
    ]


async def test_the_action_fills_the_averages_and_reports_what_it_took(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    hass.config.components.add("recorder")
    entry = await setup_account(hass, aioclient_mock)
    coordinator = coordinator_of(entry)

    with patch.object(
        coordinator, "_async_recorded_volumes", return_value=recorded(120)
    ):
        response = await hass.services.async_call(
            DOMAIN, "import_history", {}, blocking=True, return_response=True
        )
    await hass.async_block_till_done()

    (result,) = response["tanks"].values()
    assert result["days"] >= 115
    assert result["litres"] == pytest.approx(5.0 * result["days"], rel=0.05)

    published = coordinator.reading(TANK_ID)
    season = consumption.season_for(dt_util.now() - timedelta(days=10))
    assert published["seasonal_stats"][f"{season}_avg"] == pytest.approx(5.0, 0.05)
    assert published["forecast"]["fit_days"] >= 115
    assert published["days_until_empty_method"] == "seasonal"


async def test_the_action_needs_the_recorder(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await setup_account(hass, aioclient_mock)
    assert "recorder" not in hass.config.components

    with pytest.raises(HomeAssistantError) as raised:
        await hass.services.async_call(
            DOMAIN, "import_history", {}, blocking=True, return_response=True
        )

    assert raised.value.translation_key == "recorder_unavailable"


async def test_a_failed_save_leaves_the_history_as_it_was(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    hass.config.components.add("recorder")
    entry = await setup_account(hass, aioclient_mock)
    coordinator = coordinator_of(entry)
    before = list(tracker_of(coordinator).state.history)

    with (
        patch.object(coordinator, "_async_recorded_volumes", return_value=recorded(30)),
        patch.object(coordinator, "_async_persist", side_effect=OSError("disk full")),
        pytest.raises(HomeAssistantError) as raised,
    ):
        await hass.services.async_call(
            DOMAIN, "import_history", {}, blocking=True, return_response=True
        )

    assert raised.value.translation_key == "save_failed"
    assert tracker_of(coordinator).state.history == before


async def test_the_volume_statistics_are_read_in_litres_by_the_hour(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup_account(hass, aioclient_mock)
    coordinator = coordinator_of(entry)
    start = dt_util.now() - timedelta(days=30)
    hour = dt_util.start_of_local_day() - timedelta(days=1)

    instance = MagicMock()

    async def run(job, *args):
        return job(*args)

    instance.async_add_executor_job = run
    query = MagicMock(
        side_effect=lambda hass, start, end, ids, period, units, types: {
            next(iter(ids)): [
                {"start": hour.timestamp(), "mean": 990.0},
                {"start": hour.timestamp() + 3600, "mean": None},
            ]
        }
    )

    with (
        patch("homeassistant.helpers.recorder.get_instance", return_value=instance),
        patch(
            "homeassistant.components.recorder.statistics.statistics_during_period",
            query,
        ),
    ):
        samples = await coordinator._async_recorded_volumes(TANK_ID, start)

    assert samples == [(hour, 990.0)]
    _, called_start, _, ids, period, units, types = query.call_args.args
    assert called_start == start
    assert ids == {"sensor.boilerjuice_tank_volume"}
    assert (period, units, types) == ("hour", {"volume": "L"}, {"mean"})


async def test_a_tank_without_a_volume_entity_has_nothing_to_import(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup_account(hass, aioclient_mock)

    samples = await coordinator_of(entry)._async_recorded_volumes(
        "999999", dt_util.now()
    )

    assert samples == []
