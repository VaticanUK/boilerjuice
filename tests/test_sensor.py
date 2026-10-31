"""Every sensor's state, and what it does when a value is missing."""

from __future__ import annotations

from custom_components.boilerjuice.consumption import SEASONS
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .helpers import (
    TANK_ID,
    coordinator_of,
    load_fixture,
    mock_site,
    reading_of,
    setup_account,
    tank_page,
    tracker_of,
)


async def test_the_full_set_of_sensors_is_created(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_site(aioclient_mock, tank_html=load_fixture("tank_current.html"))
    await setup_account(hass, aioclient_mock)

    states = [
        state
        for state in hass.states.async_all("sensor")
        if state.entity_id.startswith("sensor.")
    ]
    assert len(states) == 21


async def test_sensor_values_come_from_the_parsed_page(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_site(aioclient_mock, tank_html=load_fixture("tank_current.html"))
    await setup_account(hass, aioclient_mock)

    def value(suffix: str) -> str:
        matches = [
            state
            for state in hass.states.async_all("sensor")
            if state.entity_id.endswith(suffix)
        ]
        assert len(matches) == 1, f"expected one {suffix}, got {matches}"
        return matches[0].state

    assert value("_oil_level") == "62.5"
    assert value("_volume") == "1562"
    assert value("_capacity") == "2500"
    assert value("_height") == "120"
    assert value("_oil_energy_content") == "10.35"
    assert value("_oil_price") == "0.62"
    assert value("_oil_cost_per_kwh") == "0.0603"
    assert value("_total_oil_consumption") == "0.0"


async def test_the_price_sensor_is_unknown_before_a_price_is_seen(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    mock_site(
        aioclient_mock,
        tank_html=tank_page(percentage=80, litres=2000),
        price_html="<html><body>no price today</body></html>",
    )
    await setup_account(hass, aioclient_mock)

    price = next(
        state
        for state in hass.states.async_all("sensor")
        if state.entity_id.endswith("_oil_price")
    )
    assert price.state == "unknown"


async def test_sensors_go_unavailable_when_the_page_stops_parsing(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup_account(hass, aioclient_mock)
    coordinator = coordinator_of(entry)

    mock_site(aioclient_mock, tank_html=load_fixture("tank_redesigned.html"))
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    level = next(
        state
        for state in hass.states.async_all("sensor")
        if state.entity_id.endswith("_oil_level")
    )
    assert level.state == "unavailable"


async def test_the_seasonal_sensor_exposes_its_breakdown(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup_account(hass, aioclient_mock)
    coordinator = coordinator_of(entry)

    mock_site(aioclient_mock, tank_html=tank_page(percentage=70, litres=1750))
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    seasonal = next(
        state
        for state in hass.states.async_all("sensor")
        if state.entity_id.endswith("_seasonal_oil_consumption")
    )
    assert "current_season_min" in seasonal.attributes
    assert "monthly_averages" in seasonal.attributes
    # The season's name belongs to the heating_season sensor now.
    assert "current_season" not in seasonal.attributes


async def test_the_heating_season_sensor_names_the_season(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The season is a state of its own, not a string inside a L/day sensor."""
    entry = await setup_account(hass, aioclient_mock)
    coordinator = coordinator_of(entry)

    mock_site(aioclient_mock, tank_html=tank_page(percentage=70, litres=1750))
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    season = next(
        state
        for state in hass.states.async_all("sensor")
        if state.entity_id.endswith("_heating_season")
    )
    assert season.state in {"winter", "spring", "summer", "autumn"}
    assert season.attributes["device_class"] == "enum"
    assert sorted(season.attributes["options"]) == [
        "autumn",
        "spring",
        "summer",
        "winter",
    ]
    assert "unit_of_measurement" not in season.attributes


async def test_the_season_is_named_even_when_it_has_no_consumption_yet(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Which season it is does not depend on how much oil has been burnt.

    The season was briefly read off the history, so a tank whose level had
    not moved since August reported an unknown season on 4 September. The
    average has nothing to report until autumn records a day; the season
    itself is on the calendar either way.
    """
    entry = await setup_account(hass, aioclient_mock)
    coordinator = coordinator_of(entry)

    mock_site(aioclient_mock, tank_html=tank_page(percentage=70, litres=1750))
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    published = {
        tank_id: {**reading, "seasonal_stats": {}}
        for tank_id, reading in coordinator.data.items()
    }
    coordinator.async_set_updated_data(published)
    await hass.async_block_till_done()

    season = next(
        state
        for state in hass.states.async_all("sensor")
        if state.entity_id.endswith("_heating_season")
    )
    seasonal = next(
        state
        for state in hass.states.async_all("sensor")
        if state.entity_id.endswith("_seasonal_oil_consumption")
    )
    assert season.state in SEASONS
    assert seasonal.state == "unknown"


def test_every_sensor_is_listed_in_the_readme() -> None:
    """A sensor nobody documented is a sensor nobody knows they have."""
    import json
    import pathlib as _pathlib

    from custom_components.boilerjuice.sensor import SENSORS

    root = _pathlib.Path("custom_components/boilerjuice")
    names = json.loads((root / "strings.json").read_text(encoding="utf-8"))["entity"][
        "sensor"
    ]
    readme = _pathlib.Path("README.md").read_text(encoding="utf-8")

    missing = [
        description.key
        for description in SENSORS
        if f"| {names[description.translation_key]['name']} |" not in readme
    ]
    assert not missing, f"not in a README table: {missing}"


async def test_every_enum_sensor_state_is_translated() -> None:
    """An untranslated option shows up in the UI as the raw value."""
    import json
    import pathlib as _pathlib

    from custom_components.boilerjuice.sensor import SENSORS

    enums = [
        description
        for description in SENSORS
        if description.device_class is SensorDeviceClass.ENUM
    ]
    assert enums, "no enum sensors found; this test has gone stale"

    for name in ("strings.json", "translations/en.json"):
        translations = json.loads(
            (_pathlib.Path("custom_components/boilerjuice") / name).read_text(
                encoding="utf-8"
            )
        )["entity"]["sensor"]
        for description in enums:
            states = translations[description.translation_key]["state"]
            assert set(states) == set(description.options or []), (
                name,
                description.key,
            )


async def test_the_last_update_sensor_reports_when_the_level_last_moved(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    entry = await setup_account(hass, aioclient_mock)
    coordinator = coordinator_of(entry)

    last_update = next(
        state
        for state in hass.states.async_all("sensor")
        if state.entity_id.endswith("_last_level_change")
    )
    assert last_update.state != "unknown"
    assert tracker_of(coordinator).last_level_change is not None


async def test_every_sensor_reports_unknown_when_there_is_no_reading(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A tank with no reading must not make any sensor raise."""
    from custom_components.boilerjuice.sensor import SENSORS, BoilerJuiceSensor

    entry = await setup_account(hass, aioclient_mock)
    coordinator = coordinator_of(entry)

    entities = [
        BoilerJuiceSensor(coordinator, TANK_ID, description) for description in SENSORS
    ]
    assert len(entities) == 33

    coordinator.data = None

    for entity in entities:
        entity.hass = hass
        assert entity.native_value is None
        assert entity.extra_state_attributes is None
        assert not entity.available


async def test_every_sensor_has_a_translated_name() -> None:
    """A missing translation shows up as a nameless entity in the UI."""
    import json
    import pathlib as _pathlib

    from custom_components.boilerjuice.sensor import SENSORS

    for name in ("strings.json", "translations/en.json"):
        translations = json.loads(
            (_pathlib.Path("custom_components/boilerjuice") / name).read_text(
                encoding="utf-8"
            )
        )
        named = translations["entity"]["sensor"]
        for description in SENSORS:
            assert description.translation_key in named, (name, description.key)


async def test_asking_a_sensor_to_update_refreshes_the_coordinator(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    from custom_components.boilerjuice.sensor import SENSORS, BoilerJuiceSensor

    entry = await setup_account(hass, aioclient_mock)
    coordinator = coordinator_of(entry)
    entity = BoilerJuiceSensor(coordinator, TANK_ID, SENSORS[0])
    entity.hass = hass

    mock_site(aioclient_mock, tank_html=tank_page(percentage=60, litres=1500))
    await entity.async_update()
    await hass.async_block_till_done()

    assert reading_of(coordinator)["total_level_percentage"] == 60


def test_every_icon_is_declared_in_icons_json() -> None:
    """Icons belong in icons.json, and must name a sensor that exists.

    A stale key here is invisible: the entity simply falls back to its
    device-class icon, which looks deliberate.
    """
    import json
    import pathlib

    from custom_components.boilerjuice.sensor import SENSORS

    icons = json.loads(
        pathlib.Path("custom_components/boilerjuice/icons.json").read_text(
            encoding="utf-8"
        )
    )["entity"]["sensor"]

    keys = {description.translation_key for description in SENSORS}
    assert set(icons) <= keys, set(icons) - keys

    # And no description sets an icon directly any more.
    assert not [d for d in SENSORS if d.icon is not None]


def test_the_platform_declares_parallel_updates() -> None:
    """Home Assistant requires the declaration, whatever the value."""
    from custom_components.boilerjuice import sensor

    assert sensor.PARALLEL_UPDATES == 0


async def test_the_forecast_sensors_follow_the_seasonal_model(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """With enough history the projection comes from the seasonal model."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    entry = await setup_account(hass, aioclient_mock)
    coordinator = coordinator_of(entry)
    tracker = tracker_of(coordinator)

    today = dt_util.start_of_local_day()
    tracker.state.history = [(today - timedelta(days=n), 10.0) for n in range(1, 31)]

    mock_site(aioclient_mock, tank_html=tank_page(percentage=70, litres=1750))
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    def state(suffix: str):
        return next(
            state
            for state in hass.states.async_all("sensor")
            if state.entity_id.endswith(suffix)
        )

    forecast = state("_forecast_oil_consumption")
    assert float(forecast.state) > 0
    assert forecast.attributes["fit_days"] == 30
    assert len(forecast.attributes["monthly_forecast"]) == 12
    assert forecast.attributes["next_12_months_total"] > 0

    days = state("_days_until_empty")
    assert days.attributes["method"] == "seasonal"
    empty = state("_projected_empty_date")
    assert empty.attributes["method"] == "seasonal"
    expected = (dt_util.now() + timedelta(days=float(days.state))).date()
    assert empty.state == expected.isoformat()


async def test_a_manual_rate_overrules_the_seasonal_model(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    entry = await setup_account(hass, aioclient_mock)
    coordinator = coordinator_of(entry)
    tracker = tracker_of(coordinator)

    today = dt_util.start_of_local_day()
    tracker.state.history = [(today - timedelta(days=n), 10.0) for n in range(1, 31)]
    tracker.state.daily_override = 25.0

    mock_site(aioclient_mock, tank_html=tank_page(percentage=70, litres=1750))
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    published = reading_of(coordinator)
    assert published["days_until_empty_method"] == "manual"
    assert published["days_until_empty"] == 70.0
    # The model is still published alongside, for comparison.
    assert published["forecast"] is not None


async def test_each_season_and_month_has_its_own_average_sensor(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A season or month never recorded is unknown, not zero."""
    from datetime import datetime

    from homeassistant.util import dt as dt_util

    entry = await setup_account(hass, aioclient_mock)
    coordinator = coordinator_of(entry)
    tracker = tracker_of(coordinator)

    def last(month: int, date: int) -> datetime:
        """Return the most recent past `date` of `month`, inside the history window."""
        now = dt_util.now()
        moment = datetime(now.year, month, date, tzinfo=now.tzinfo)
        return moment if moment < now else moment.replace(year=now.year - 1)

    tracker.state.history = [
        (last(1, 10), 30.0),
        (last(1, 11), 20.0),
        (last(2, 10), 16.0),
        (last(7, 10), 2.0),
    ]

    mock_site(aioclient_mock, tank_html=tank_page(percentage=70, litres=1750))
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    def state(suffix: str):
        return next(
            state
            for state in hass.states.async_all("sensor")
            if state.entity_id.endswith(suffix)
        )

    winter = state("_winter_average_oil_consumption")
    assert winter.state == "22.0"
    assert winter.attributes["min"] == 16.0
    assert winter.attributes["max"] == 30.0
    assert state("_summer_average_oil_consumption").state == "2.0"
    assert state("_spring_average_oil_consumption").state == "unknown"

    # The monthly sensors are registered but off until somebody wants them.
    from custom_components.boilerjuice.sensor import SENSORS
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    months = [
        d for d in SENSORS if d.key.endswith("_average") and d.key[:-8] not in SEASONS
    ]
    assert len(months) == 12
    for description in months:
        entity_id = registry.async_get_entity_id(
            "sensor", "boilerjuice", f"{TANK_ID}_{description.key}"
        )
        assert entity_id is not None
        assert (
            registry.async_get(entity_id).disabled_by
            is er.RegistryEntryDisabler.INTEGRATION
        )

    published = reading_of(coordinator)
    by_key = {d.key: d for d in months}
    assert by_key["january_average"].value(published) == 25.0
    assert by_key["february_average"].value(published) == 16.0
    assert by_key["march_average"].value(published) is None
