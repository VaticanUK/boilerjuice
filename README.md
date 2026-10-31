# BoilerJuice Integration for Home Assistant

[![CI](https://github.com/willbeeching/boilerjuice/actions/workflows/ci.yaml/badge.svg)](https://github.com/willbeeching/boilerjuice/actions/workflows/ci.yaml)
[![GitHub Release](https://img.shields.io/github/v/release/willbeeching/boilerjuice)](https://github.com/willbeeching/boilerjuice/releases)
[![Downloads](https://img.shields.io/github/downloads/willbeeching/boilerjuice/total?label=downloads)](https://github.com/willbeeching/boilerjuice/releases)
[![Installs](https://img.shields.io/badge/dynamic/json?color=41BDF5&logo=home-assistant&label=installs&suffix=%20homes&url=https%3A%2F%2Fanalytics.home-assistant.io%2Fcustom_integrations.json&query=%24.boilerjuice.total)](https://analytics.home-assistant.io/)
[![License](https://img.shields.io/github/license/willbeeching/boilerjuice)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)

Monitors heating oil tanks registered with
[BoilerJuice](https://www.boilerjuice.com/), the UK domestic heating oil
supplier, and reports level, volume, consumption, energy content and cost in
Home Assistant.

## How it works, and what that costs you

BoilerJuice has no public API. This integration signs into your account with
your email and password and reads the tank page, once an hour.

That has consequences worth knowing before you install it:

- **It can break when BoilerJuice changes its website.** When that happens
  readings stop and a repair notification appears under Settings. Your
  consumption history is not lost: the integration refuses to record a
  reading it could not parse, rather than treating an unreadable page as an
  empty tank.
- **Your BoilerJuice password is stored by Home Assistant**, in the same
  plain-text config entry store every other login-based integration uses.
  See [SECURITY.md](SECURITY.md) for exactly what is stored, sent and
  logged.
- **Readings are only as fresh as BoilerJuice makes them.** The underlying
  tank level changes far less often than hourly, which is why consumption is
  derived from level changes rather than from poll timing.

## Requirements

- Home Assistant 2025.2.5 or newer. Both that version and the current
  release are tested in CI on every change.
- A BoilerJuice account with at least one tank set up.

## Installation

### HACS

BoilerJuice is not in the HACS default list, so add it as a custom
repository:

1. Open HACS.
2. Three dots menu, top right, then **Custom repositories**.
3. Add `https://github.com/willbeeching/boilerjuice` with category
   **Integration**.
4. Find BoilerJuice and click **Download**.
5. Restart Home Assistant.

### Manual

1. Download `boilerjuice.zip` from the
   [latest release](https://github.com/willbeeching/boilerjuice/releases) and
   extract it into `config/custom_components/`. Every release lists the
   archive's SHA-256 digest so you can check what you downloaded.
2. Restart Home Assistant.

### Adding your account

1. **Settings**, then **Devices & Services**, then **Add Integration**.
2. Search for BoilerJuice.
3. Enter your account email and password.

Setup fails if the credentials are rejected, if BoilerJuice cannot be
reached, or if the account has no tanks, so a successful setup means the
scrape worked.

One config entry is one BoilerJuice account. Every tank on the account
becomes its own device with its own sensors and its own consumption history.

### Removing it

**Settings**, **Devices & Services**, BoilerJuice, three dots, **Delete**.
That removes the account's devices and entities and deletes its stored
consumption history. Nothing is left behind, and nothing is changed on the
BoilerJuice website.

## Configuration

Set at the time you add the account:

| Option | Required | Default | Notes |
| --- | --- | --- | --- |
| Email | Yes | — | BoilerJuice account email |
| Password | Yes | — | BoilerJuice account password |
| kWh per litre | No | `10.35` | Energy content of your oil, between 0.1 and 100. Kerosene is about 10.35, gas oil about 10.7. A value outside that range, or one carried over from a version before the range existed, falls back to the default with a warning in the log |

Changed afterwards through **Reconfigure** on the integration entry:

| Option | Notes |
| --- | --- |
| Password | Leave blank to keep the current one |
| kWh per litre | Applied to oil burnt from the next poll on, not retrospectively |
| Tanks to track | Which of the account's tanks get entities. Excluding a tank removes its device on the next poll and keeps its history in case you put it back |

If BoilerJuice stops accepting your password, Home Assistant raises a
**Reconfigure**-style repair asking for the new one. It does not silently
retry for ever.

Multiple accounts are supported. Each keeps its own login session, cookie
jar and stored history.

## Supported tanks

Whatever BoilerJuice itself supports. The integration reads what the tank
page reports and does not model tank shapes itself; the shape, model and
manufacturer are read from the page as attributes. A tank BoilerJuice tracks
is a tank this integration can read.

## Sensors

One set per tank.

### Tank

| Sensor | Unit | Notes |
| --- | --- | --- |
| Oil level | % | Not a battery device class: a tank is not a cell |
| Volume | L | Current volume of oil |
| Capacity | L | Total tank capacity (diagnostic) |
| Height | cm | Physical tank height (diagnostic) |

### Consumption

| Sensor | Unit | Notes |
| --- | --- | --- |
| Daily oil consumption | L/day | Rolling 7-day average. Unknown until a complete day has been measured. `sample_days` says how much evidence is behind it |
| Total oil consumption | L | Accumulates since the last reset |
| Total oil energy | kWh | Accumulated using the kWh per litre in force at the time. **This is the Energy dashboard sensor** |
| Seasonal oil consumption | L/day | Current season's average, with per-season and per-month averages and litres per calendar month (`monthly_totals`) as attributes. Unknown until a day in this season has been recorded, which on 1 September means waiting for the first autumn reading |
| Forecast oil consumption | L/day | What the seasonal model expects the tank to burn today. Its attributes carry the fitted cycle and the litres expected in each of the next 12 months. Unknown until 14 complete days have been recorded. See [Seasonal forecast](#seasonal-forecast) |
| Days until empty | d | When the forecast says the current volume runs out. The `method` attribute says which estimate it came from |
| Projected empty date | — | The same projection as a date, for calendars and automations |

### Seasonal and monthly averages

One sensor per season and one per calendar month, each the average L/day over
every recorded day in it. The twelve monthly sensors are disabled by default;
enable the ones you want under the tank's device page. A season or month the integration has not yet seen
reports unknown, not zero. The season sensors carry the lightest and heaviest
day as `min` and `max` attributes. Each averages across the two years of
history: January's sensor is every recorded January day, in either year.

| Sensor | Unit |
| --- | --- |
| Winter average oil consumption | L/day |
| Spring average oil consumption | L/day |
| Summer average oil consumption | L/day |
| Autumn average oil consumption | L/day |
| January average oil consumption | L/day |
| February average oil consumption | L/day |
| March average oil consumption | L/day |
| April average oil consumption | L/day |
| May average oil consumption | L/day |
| June average oil consumption | L/day |
| July average oil consumption | L/day |
| August average oil consumption | L/day |
| September average oil consumption | L/day |
| October average oil consumption | L/day |
| November average oil consumption | L/day |
| December average oil consumption | L/day |

### Price and energy

| Sensor | Unit |
| --- | --- |
| Oil price | GBP/L |
| Oil energy content | kWh/L |
| Oil cost per kWh | GBP/kWh |

### Diagnostic

| Sensor | Notes |
| --- | --- |
| Last level change | When the tank level last changed. It is normal for this to sit still for days |
| Last successful update | When the account was last polled successfully |
| Heating season | Winter, spring, summer or autumn, read off the calendar. Always set, whether or not the season has recorded any consumption yet |

## How consumption tracking works

BoilerJuice only reports a new tank level occasionally, so consumption is
inferred from the change between two readings and then apportioned across the
period it spanned.

```
Dec 1, 09:00   Tank at 850 L        reference saved
Dec 2 - Dec 5  Reading unchanged    reference stays at 850 L
Dec 6, 09:00   Tank at 800 L        50 L used over the last 5 days
```

That 50 L is split across the days by how much of the interval fell in each,
so the parts add back to exactly 50 L:

```
Dec 1   6.25 L   (09:00 to midnight)
Dec 2  10.00 L
Dec 3  10.00 L
Dec 4  10.00 L
Dec 5  10.00 L
Dec 6   3.75 L   (midnight to 09:00)
```

Those daily totals feed the rolling 7-day average behind Daily oil
consumption, and the per-season buckets behind Seasonal oil consumption.

Other behaviour worth knowing:

- The rolling average uses complete days only. Today's bucket is still
  filling, so including it would drag the rate down: a day three hours old
  holds three hours of oil but would carry a full day of weight.
- Refills are detected rather than counted as negative consumption. When the
  level rises, the reference resets without discarding history.
- The reference only moves when the level moves, so a flat reading does not
  dilute the rate.
- A tank that disappears from your account is retired, not erased: its
  device goes but its consumption history is kept, and it resumes if the
  tank comes back. Nothing a scraped page says will delete that history.
- A drop spanning midnight is split between the two days by the time in
  each, not credited whole to the day it was noticed.
- Weighting is by elapsed time, so a 23- or 25-hour daylight-saving day
  neither gains nor loses oil.
- Dated history is kept for two years and a month (765 days), collapsed to
  one row per day, so every season and calendar month has two complete
  instances to average and the forecast sees each winter twice.

### Seasonal forecast

A tank that burns 8 L a day in October will burn far more in January, so
dividing what is left by last week's average says the oil lasts longer than
it will in autumn, and runs out sooner than it will in spring. The forecast
instead models a day's burn as an average plus one annual wave:

```
burn(day) = average + swing × cos(time of year − peak)
```

and fits the average, the size of the swing and the date of the peak to the
daily history by least squares.

Six weeks of autumn cannot say where winter peaks, so until the history
covers the year the fit leans on a default shape: a peak in mid January, the
coldest weeks burning 160% of the average and high summer (hot water only)
40%. That default counts as 30 days of evidence. With a few weeks of history
it is the shape, scaled so it reproduces what your tank actually burnt; with
a year of history your tank's own cycle has overruled it.

The fitted wave is the normal year. On top of it the forecast compares the
last seven complete days with what the wave expected for them. If the last
week ran 30% hot, today's forecast is 30% up, and the difference halves
every 14 days going forward: a cold snap moves next week's estimate and
barely touches next winter's. That ratio is clamped between half and double,
so one odd week cannot run away with it.

Days until empty walks that forecast forward a day at a time until it has
burnt what is in the tank. The `method` attribute says which estimate was
used:

| Method | When |
| --- | --- |
| `seasonal` | 14 or more complete days of history. The normal case |
| `recent_average` | Less history than that: volume divided by the rolling 7-day rate |
| `manual` | A daily rate set with `set_consumption` overrules everything, the seasonal model included |
| `capacity_estimate` | No history at all: 2% of capacity a day |

The forecast sensor's attributes show what the model has learnt:

| Attribute | Meaning |
| --- | --- |
| `annual_average` | The average daily burn across the year, in L/day |
| `seasonal_swing_percent` | How far the peak sits above that average. 60 means the coldest weeks burn 160% of it |
| `peak` | The day of the year the tank burns most |
| `recent_vs_expected` | Last week's burn over what the model expected for it. 1.2 is 20% above |
| `fit_days` | Complete days of history the fit used |
| `months_covered` | How many calendar months they span. Until this approaches 12 the default shape is doing much of the work |
| `monthly_forecast` | Litres expected in each of the next 12 calendar months, starting with this one |
| `next_12_months_total` | Their sum, for budgeting a year's oil |

### What the estimates cannot tell you

- **The forecast knows the calendar, not the weather.** It has learnt what a
  normal November looks like for your house and carries a recent cold or mild
  spell forward for a few weeks. It cannot see next month's weather, and an
  unusually hard winter will beat it.
- **Change how you heat the house and the forecast lags.** New boiler, new
  insulation, someone now working from home: the fit averages the last two
  years, so it takes months for a change like that to show fully. The recent
  adjustment picks up the difference in the meantime, within its half-to-double
  bounds.
- **A forecast past two years is not given.** If the model has learnt that
  the tank burns next to nothing, days until empty reports unknown rather
  than a number in the thousands.
- **Before any history exists** it falls back to assuming 2% of tank capacity
  a day. That is a placeholder, not a measurement.
- **Consumption is inferred, not metered.** It is the difference between two
  readings BoilerJuice published, so its resolution is theirs.
- **Seasonal averages need time.** Seasons are Winter (Dec to Feb), Spring
  (Mar to May), Summer (Jun to Aug) and Autumn (Sep to Nov). A season reports
  unknown until the integration has observed consumption during it. On a
  fresh install the current season populates quickly and the other three fill
  in as the year goes round. This is a data availability limit, not a fault.
- **A season goes quiet at its boundary.** Consumption is only recorded when
  BoilerJuice reports a lower level, and on a large tank a slow burn can take
  a week to show up. Between 1 September and the first detected autumn drop,
  the seasonal sensor has no autumn to report. When that drop arrives the
  litres are spread back over every day since the last one, so the days in
  between fill in retroactively rather than being lost.
- **A page we cannot read is described, not quoted.** When the tanks page
  or a tank page arrives in a shape the parser does not recognise, the
  warning carries a summary of the page: its size, how many forms, links
  and tank links it holds, and whether it matches a known interstitial such
  as a Cloudflare challenge or a maintenance notice. Page HTML is never
  logged, so the summary is counts and fixed words only, and is safe to
  paste into an issue.
- **Diagnostics say where the history reaches.** `history_span` and
  `history_rows_by_month` in the diagnostics download show which months hold
  data. A month missing from the middle is history that went away; months
  missing from the end are months that have not recorded anything yet.

## Actions

### `boilerjuice.reset_consumption`

Zeroes the consumption counters for the target, clears any manual daily
override, and takes the current level as the new baseline. The dated history
behind the seasonal and monthly averages is kept.

```yaml
action: boilerjuice.reset_consumption
target:
  device_id: <your BoilerJuice tank>
```

Pass `clear_history: true` to delete the dated history as well. It takes two
years to rebuild in full, so reach for it only when the history itself is wrong,
not to zero a counter.

```yaml
action: boilerjuice.reset_consumption
target:
  device_id: <your BoilerJuice tank>
data:
  clear_history: true
```

A device or entity target resets that tank. Targeting the config entry resets
every tank on the account. With more than one account configured a target is
required: this action rewrites stored history, so it will not guess.

All three actions apply to one account per call. A target that reaches two of them,
whether as a list of entry IDs or through an area or floor holding tanks from
each, is refused with nothing changed. Accounts are written one at a time and
a document already on disk cannot be put back, so a call that failed half way
would leave you worse off than one that never started. Areas, floors and
labels all resolve to the tanks under them; a target that resolves to no
BoilerJuice tank is an error, never a licence to reset everything.

### `boilerjuice.set_consumption`

Seeds the counters with known values, for example after a reset or after
moving from another integration.

```yaml
action: boilerjuice.set_consumption
target:
  device_id: <your BoilerJuice tank>
data:
  liters: 500 # Total litres consumed
  daily: 15 # Optional: daily rate in L/day
```

`daily` is a **persistent override**. It replaces the measured rate and
survives polls and restarts until you run `reset_consumption`. Leave it out
to keep using the measured rate.

### `boilerjuice.import_history`

Rebuilds the per-day history for the days before the integration's own
history begins, from the tank volume Home Assistant's recorder has kept.
Run it once after installing on a system that has been recording the tank
for a while, or after a version that kept only 30 days of history (anything
before 16 August 2026) has thrown the rest away. The seasonal and monthly
averages and the forecast then have months to work from instead of starting
from nothing.

```yaml
action: boilerjuice.import_history
target:
  device_id: <your BoilerJuice tank>
```

It reads the hourly long-term statistics of the tank's **Volume** sensor,
which the recorder keeps indefinitely, and replays them the way a live
poll would: each fall in volume is oil burnt, spread over the days since
the level last moved; a rise of 100 L or more is a delivery; a smaller rise
is the reading wobbling and is ignored, so the same litres are never
counted twice.

What it will and will not touch:

- **Only earlier days.** Days already in the history, and days since the
  last level change (which the next detected drop will fill), are left
  alone, so running it twice changes nothing.
- **Not the totals.** Total oil consumption and Total oil energy count from
  the last reset and feed the Energy dashboard; restating them would show
  months of oil arriving at once.
- **Only what the recorder kept.** Nothing older than the two-year history
  window, and nothing from before the Volume sensor existed.

Run it from Developer tools, Actions, with **Return response** ticked, to
see how many days and litres were imported for each tank.

## Automation examples

Warn when the tank is getting low:

```yaml
automation:
  - alias: Oil tank running low
    triggers:
      - trigger: numeric_state
        entity_id: sensor.garden_tank_oil_level
        below: 25
    actions:
      - action: notify.persistent_notification
        data:
          message: >-
            Oil tank at {{ states('sensor.garden_tank_oil_level') }}%,
            about {{ states('sensor.garden_tank_days_until_empty') }} days left.
```

Order before winter bites, using the days-until-empty estimate:

```yaml
automation:
  - alias: Time to order oil
    triggers:
      - trigger: numeric_state
        entity_id: sensor.garden_tank_days_until_empty
        below: 21
    conditions:
      - condition: numeric_state
        entity_id: sensor.garden_tank_oil_price
        below: 0.65
    actions:
      - action: notify.mobile_app
        data:
          message: >-
            Three weeks of oil left and the price is
            {{ states('sensor.garden_tank_oil_price') }} a litre.
```

Add the tank to the Energy dashboard by configuring **Total oil energy** as a
gas or energy source under Settings, Dashboards, Energy.

## Upgrading

### To 2.0.0

This is a breaking release. Read this section before upgrading.

**One config entry is now one account, and every tank on it is a device.**
Previously the integration picked the first tank and ignored the rest. If
your account has more than one tank you will get devices and entities for all
of them on the first poll after upgrading. Use **Reconfigure** to narrow that
down.

**Existing entities keep their entity IDs.** Entities and devices are keyed
by tank ID, which has not changed, so dashboards and automations keep
working. Their unique IDs move from Python class names to stable keys, which
Home Assistant handles automatically on first start.

**Two entities change:**

| Entity | Change |
| --- | --- |
| `sensor.<tank>_oil_consumption_kwh` | **Removed.** It accumulated its value as a side effect of being read, so what it reported depended on how often something looked at it. Use **Total oil energy** on the Energy dashboard instead, now that its conversion honours your configured kWh per litre |
| `sensor.<tank>_last_updated` | Renamed to **Last level change**, which is what it has always measured. A new **Last successful update** sensor reports when the account was last polled |
| `sensor.<tank>_seasonal_oil_consumption` | Its `current_season` attribute is gone. The season is now a **Heating season** sensor, so it can be translated and graphed: read `states('sensor.<tank>_heating_season')` instead of `state_attr('sensor.<tank>_seasonal_oil_consumption', 'current_season')`. The seasonal and monthly averages stay where they are |

If the Energy dashboard was configured against the removed sensor, point it
at Total oil energy. Its historical statistics do not carry across.

**`reset_consumption` no longer deletes the seasonal history.** It zeroes the
counters and references and leaves the dated history alone, because the two
answer different questions and the history takes a year to rebuild. Pass
`clear_history: true` for the old behaviour. If you have an automation that
resets the counter after each refill, it has been quietly costing you the
seasonal averages until now.

**Two repairs appear on the first start after upgrading.** Home Assistant
raises one because **Height** no longer has a state class (it is a fixed
number from your tank's configuration, so recording a statistic for it was
recording a constant), and one because **Days until empty** now reports its
unit as `d` rather than `days`. Take the offered action on both: delete the
height statistics, and update the unit on days until empty if that option is
offered so its history carries across. Neither comes back.

Upgrading from a release made between April and December 2025 raises a
third: **Seasonal oil consumption** was labelled in `L` then, although its
values were always litres per day. Choose to update the unit to `L/day`
rather than delete: the old numbers mean what the new label says, so
relabelling keeps that history correct.

**Other changes you will notice:**

- Oil level is no longer a battery device class, so it leaves battery
  dashboards and low-battery alerts.
- Sensors report unknown rather than 0 when there is nothing to report: a
  daily rate before a complete day has been measured, a season with no data.
- Changing kWh per litre now affects every kWh figure. Previously the total
  was hard-coded to 10.35 while the cost sensors used your configured value.
  It applies to oil burnt from that point on, not retrospectively: Total oil
  energy is a `total_increasing` sensor, so restating its history would show
  up in long-term statistics as a jump, or as a meter reset if the number
  went down.
- Consumption history moves to a per-account storage document, automatically,
  on first start. If it cannot be read it is discarded and you get a repair
  notification saying so, rather than the history silently resetting.
- YAML configuration is deprecated. It still imports once, and logs a warning
  asking you to remove the block.

### To 1.3.2

A failed scrape could be accepted as a valid reading: a page the parser did
not understand became "0 litres, 0%", and the drop from the last good reading
to that zero was recorded as real consumption. If your history contains an
implausible spike, run `boilerjuice.reset_consumption` with
`clear_history: true` and re-seed with `boilerjuice.set_consumption`.

### To 1.3.1

Days until empty had two implementations, and the one the sensor used fell
back to a hard-coded 510 L rather than your tank's real capacity. It only
showed on a fresh install, before any consumption history exists.

### To 1.3.0

- Seasonal oil consumption now works. It previously reported unknown on most
  polls and could only ever populate one season.
- Consumption figures shift slightly. Multi-day consumption used to be
  over-attributed; daily totals are now conserved exactly.
- Setup now rejects bad credentials, rather than creating an entry that
  silently never updates.

### From 1.0.x

Duplicate sensors were merged:

| Old | New |
| --- | --- |
| `sensor.<tank>_total_oil_level`, `sensor.<tank>_usable_oil_level` | `sensor.<tank>_oil_level` |
| `sensor.<tank>_usable_oil_volume` | `sensor.<tank>_volume` |

## Troubleshooting

| Symptom | Cause or fix |
| --- | --- |
| A "sign in again" repair appeared | Your BoilerJuice password changed, or the account was locked. Click through the repair and enter the current password |
| A "BoilerJuice has changed its website" repair appeared | The site's layout moved, on the tank page or the tank list. Readings stop, but nothing is deleted: history is kept and devices stay. Check for an integration update; if there is not one, open a "Readings have stopped" issue |
| A "consumption history was reset" repair appeared | The stored history could not be read and was discarded. Current readings are unaffected. Re-seed the totals with `boilerjuice.set_consumption` if you know them |
| One tank unavailable, the others fine | That tank could not be read. Its history is safe; it becomes available again on the first successful poll. The log carries one warning per outage, not one per hour |
| Entities unavailable | The last poll failed. Check the logs; the integration retries hourly |
| Consumption stuck at 0 | Expected until BoilerJuice publishes a lower level than the one recorded as the reference |
| Daily consumption unknown | Expected until a complete day has been measured. `sample_days` on the sensor says how many days it has |
| Last level change not moving | Expected. It tracks level changes, not polls. Use Last successful update to check polling |
| Seasonal averages unknown | Expected for seasons the integration has not lived through yet |

### Recovering from a bad history

If consumption looks wrong, for example after upgrading from a version that
could record a phantom reading:

1. Run `boilerjuice.reset_consumption` against the tank with
   `clear_history: true`. That clears its counters, references and dated
   history. Without the flag the history is kept, which is what you want if
   only the running total is wrong.
2. Optionally run `boilerjuice.set_consumption` with the total you believe is
   correct, so long-term statistics continue from the right place.
3. Leave it a day. The daily rate reappears once a complete day has been
   measured, and seasons refill as the year goes round.

The tank's current level, volume and capacity are read fresh every poll and
are never affected by any of this.

### Debug logging

```yaml
logger:
  default: info
  logs:
    custom_components.boilerjuice: debug
```

### Getting help

Open an issue using one of the templates. Attach the diagnostics download
(**Settings**, **Devices & Services**, BoilerJuice, three dots, **Download
diagnostics**): it is written to contain no email address, password, tank ID,
tank name, cookie or page HTML, so it is safe to post publicly.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the module layout and the
two invariants the code depends on.

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements-dev.txt -r requirements-test.txt
.venv/bin/ruff format custom_components tests scripts
.venv/bin/ruff check custom_components tests scripts
.venv/bin/mypy
.venv/bin/python -m pytest
```

The two test lanes need different Python versions (3.14 for current Home
Assistant, 3.13 for the 2025.2.5 floor), so they need separate environments.
See [CONTRIBUTING.md](CONTRIBUTING.md).

The test suite is entirely offline: it uses sanitised HTML fixtures, blocks
sockets, and needs no BoilerJuice credentials. Coverage is enforced at 95%
per module, on both lanes.

`quality_scale.yaml` tracks this integration against the
[Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/)
rule by rule. The manifest deliberately claims no quality scale while any
Bronze rule is still outstanding.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). CI must pass.

## Security

See [SECURITY.md](SECURITY.md) for how credentials are handled and how to
report a vulnerability.

## License

MIT, see [LICENSE](LICENSE).
