"""The consumption maths.

Pure functions over readings, timestamps and stored history: no network, no
Home Assistant, no mutation of anything the caller did not hand in. The
coordinator decides when to apply the results; this module only computes.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .models import TankReading

# Number of days to keep in the rolling average.
CONSUMPTION_ROLLING_DAYS = 7

# Dated history is kept for two years and a month, so every season and every
# calendar month has two complete instances to average and the seasonal fit
# sees each winter twice. Entries are collapsed to one per day, so this
# bounds the stored history at ~765 rows, inside storage's MAX_HISTORY_ROWS.
SEASONAL_HISTORY_DAYS = 2 * 365 + 35

WINTER_MONTHS = (12, 1, 2)
SPRING_MONTHS = (3, 4, 5)
SUMMER_MONTHS = (6, 7, 8)
AUTUMN_MONTHS = (9, 10, 11)

SEASONS = ("winter", "spring", "summer", "autumn")

# Without measured consumption, assume a day burns this share of the tank.
FALLBACK_DAILY_SHARE_OF_CAPACITY = 0.02

# The seasonal forecast models daily burn as a mean plus one annual sine
# wave. Until the history covers enough of the year to say where the peak
# falls and how deep the summer trough goes, the wave takes this shape: a
# UK heating year peaking in mid January, with the coldest weeks burning
# 160% of the mean and high summer (hot water only) 40%.
YEAR_DAYS = 365.25
PRIOR_PEAK_DAY_OF_YEAR = 15
PRIOR_AMPLITUDE_RATIO = 0.6
# How many days of evidence that default shape is worth. Small enough that
# a full year of history overrules it, large enough that a few weeks of
# October cannot invent a winter.
PRIOR_WEIGHT_DAYS = 30
# Fewer complete days than this and the seasonal model is not attempted.
SEASONAL_MIN_DAYS = 14
# A recent run above or below the model (a cold snap, a week away) is
# assumed to persist, fading by half every this many days.
ANOMALY_HALF_LIFE_DAYS = 14
# Bounds on that anomaly, so one odd week cannot halve or triple a forecast.
ANOMALY_MIN = 0.5
ANOMALY_MAX = 2.0
# Beyond two years a projection says nothing useful.
FORECAST_HORIZON_DAYS = 730
FORECAST_MONTHS = 12

DatedHistory = list[tuple[datetime, float]]


@dataclass(frozen=True, slots=True)
class Transition:
    """What changed between the previous references and a new reading."""

    litres_consumed: float = 0.0
    litres_added: float = 0.0
    source: str | None = None

    @property
    def is_consumption(self) -> bool:
        """Whether oil was burnt between the two readings."""
        return self.litres_consumed > 0

    @property
    def is_refill(self) -> bool:
        """Whether the tank gained oil between the two readings."""
        return self.litres_added > 0


UNCHANGED = Transition()


def elapsed_seconds(later: datetime, earlier: datetime) -> float:
    """Return the real seconds between two aware datetimes.

    Both are converted to UTC first. Subtracting two aware datetimes that
    share a tzinfo object makes CPython ignore the zone and subtract them as
    if they were naive, which returns wall-clock time: the 23-hour day when
    the clocks go forward measures 24 hours, and the 25-hour day measures 24
    as well. That is exactly the arithmetic the day-weighting must not do.
    """
    return (later.astimezone(UTC) - earlier.astimezone(UTC)).total_seconds()


def season_for(moment: datetime) -> str:
    """Return the season a date falls in."""
    month = moment.month
    if month in WINTER_MONTHS:
        return "winter"
    if month in SPRING_MONTHS:
        return "spring"
    if month in SUMMER_MONTHS:
        return "summer"
    return "autumn"


def classify(
    previous_volume: float | None,
    previous_level: float | None,
    reading: TankReading,
) -> Transition:
    """Describe the move from the previous references to `reading`.

    The direct volume change is the more precise signal and wins when both
    are available. The percentage only becomes litres when the page also gave
    us a capacity, so a partial page contributes nothing rather than
    contributing a guess.
    """
    volume = reading.volume_litres
    if volume is not None and previous_volume is not None:
        if volume > previous_volume:
            return Transition(litres_added=volume - previous_volume, source="volume")
        if volume < previous_volume:
            return Transition(litres_consumed=previous_volume - volume, source="volume")
        return UNCHANGED

    level = reading.level_percentage
    capacity = reading.capacity_litres
    if level is not None and previous_level is not None and capacity is not None:
        if level > previous_level:
            return Transition(
                litres_added=(level - previous_level) / 100 * capacity, source="level"
            )
        if level < previous_level:
            return Transition(
                litres_consumed=(previous_level - level) / 100 * capacity,
                source="level",
            )

    return UNCHANGED


def allocate_over_days(
    litres: float, since: datetime | None, now: datetime
) -> DatedHistory:
    """Apportion `litres` across the days it was actually burnt over.

    Consumption is only ever observed as a drop between two polls, so oil
    burnt while Home Assistant was down (or between sparse tank readings)
    belongs to the days it spanned rather than to the day we noticed it.

    Each calendar day is weighted by the real time the interval spent inside
    it, so the shares sum back to exactly `litres` and a daylight-saving day
    gets the share its 23 or 25 hours earned rather than a flat 24.

    The shortcut is taken on the calendar date, not on the length of the
    interval. Testing "under 24 hours" put a 23:30 to 00:30 drop entirely on
    the second day, which is a real misallocation on the busiest hours of a
    winter evening.
    """
    if since is None:
        return [(now, litres)]

    interval_seconds = elapsed_seconds(now, since)
    if interval_seconds <= 0:
        # The clock went backwards. There is no interval to spread over.
        return [(now, litres)]
    if since.date() == now.date():
        # Both samples fall on one calendar day, so there is nothing to split.
        return [(now, litres)]

    allocated: DatedHistory = []
    day = since.date()
    last_day = now.date()
    while day <= last_day:
        day_start = datetime.combine(day, datetime.min.time(), tzinfo=since.tzinfo)
        day_end = day_start + timedelta(days=1)
        overlap = elapsed_seconds(min(now, day_end), max(since, day_start))
        if overlap > 0:
            allocated.append((day_start, litres * overlap / interval_seconds))
        day += timedelta(days=1)
    return allocated


def daily_totals(history: DatedHistory) -> dict[str, float]:
    """Group dated consumption into one total per calendar day."""
    totals: dict[str, float] = {}
    for moment, litres in history:
        key = moment.date().isoformat()
        totals[key] = totals.get(key, 0.0) + litres
    return dict(sorted(totals.items()))


def rolling_window(
    totals: dict[str, float], now: datetime, window: int = CONSUMPTION_ROLLING_DAYS
) -> list[float]:
    """Return the daily figures the rolling rate should average.

    Today's bucket is still filling, so averaging it alongside finished days
    drags the rate down: a day that is three hours old contributes three
    hours of oil but a full day of weight. Earlier days do fill in, because
    the next detection interval starts where the last one ended and tops up
    that day's bucket. On a fresh install today may be all there is, and
    reporting a partial day beats reporting nothing.
    """
    today = now.date().isoformat()
    complete_days = [litres for date, litres in totals.items() if date < today]
    return (complete_days or list(totals.values()))[-window:]


def average(values: list[float]) -> float:
    """Return the mean of `values`, or 0.0 when there are none."""
    return sum(values) / len(values) if values else 0.0


def trim_history(
    totals: dict[str, float],
    now: datetime,
    midnight: Callable[[str], datetime],
) -> DatedHistory:
    """Collapse history to one entry per day and drop anything too old.

    Seasonal averages need every season represented, so a short window would
    leave three of the four empty. The daily rollup is what every consumer
    reads anyway, so this loses nothing and bounds the stored rows.
    """
    cutoff = now - timedelta(days=SEASONAL_HISTORY_DAYS)
    return [
        (day_start, litres)
        for day_start, litres in (
            (midnight(date), litres) for date, litres in totals.items()
        )
        if day_start >= cutoff
    ]


def seasonal_stats(
    totals: dict[str, float],
    now: datetime,
    midnight: Callable[[str], datetime],
) -> dict[str, Any]:
    """Summarise consumption by season and by month."""
    if not totals:
        return {}

    stats: dict[str, Any] = {season: [] for season in SEASONS}
    stats["monthly"] = {}
    # Litres per calendar month, year by year. The averages above merge
    # every January into one figure; these keep last winter apart from this
    # one. The first and current months are partial and say so by being low.
    monthly_totals: dict[str, float] = {}
    # None, not 0.0: a season we have never seen is unknown, and publishing
    # zero would claim the tank measurably burnt nothing all winter.
    stats["current_season"] = {"avg": None, "min": None, "max": None}

    for day, litres in totals.items():
        moment = midnight(day)
        stats[season_for(moment)].append(litres)
        stats["monthly"].setdefault(moment.strftime("%B"), []).append(litres)
        month = day[:7]
        monthly_totals[month] = monthly_totals.get(month, 0.0) + litres

    stats["monthly_totals"] = {
        month: round(litres, 1) for month, litres in monthly_totals.items()
    }

    for season in SEASONS:
        if stats[season]:
            stats[f"{season}_avg"] = round(statistics.mean(stats[season]), 1)
            stats[f"{season}_min"] = round(min(stats[season]), 1)
            stats[f"{season}_max"] = round(max(stats[season]), 1)

    for month, values in stats["monthly"].items():
        stats["monthly"][month] = round(statistics.mean(values), 1)

    # The same averages keyed by month number, for the per-month sensors.
    # "%B" follows the system locale, so a name is no key to look one up by.
    by_number: dict[int, list[float]] = {}
    for day, litres in totals.items():
        by_number.setdefault(int(day[5:7]), []).append(litres)
    stats["month_avg"] = {
        month: round(statistics.mean(values), 1)
        for month, values in sorted(by_number.items())
    }

    current = season_for(now)
    if stats[current]:
        stats["current_season"] = {
            "avg": round(statistics.mean(stats[current]), 1),
            "min": round(min(stats[current]), 1),
            "max": round(max(stats[current]), 1),
        }

    return stats


def days_until_empty(
    volume_litres: int | None,
    capacity_litres: int | None,
    level_percentage: float | None,
    daily_litres: float,
) -> float | None:
    """Estimate how long the remaining oil lasts."""
    if volume_litres is None:
        return None

    if daily_litres > 0:
        return round(volume_litres / daily_litres, 1)

    if capacity_litres and level_percentage is not None and level_percentage > 0:
        return round(
            volume_litres / (capacity_litres * FALLBACK_DAILY_SHARE_OF_CAPACITY), 1
        )

    return None


# --- importing from recorded volumes ----------------------------------------

# A recorded rise smaller than this is the reading wobbling, not a delivery.
# BoilerJuice reports in steps of about 10 L and can step back up by one;
# treating that as a refill would book the next step down a second time.
IMPORT_REFILL_THRESHOLD_LITRES = 100.0


def history_from_volumes(samples: list[tuple[datetime, float]]) -> DatedHistory:
    """Rebuild dated consumption from a series of recorded tank volumes.

    The same bookkeeping a live poll does, replayed: a fall below the
    reference is oil burnt, spread over the days since the reference last
    moved; a rise of IMPORT_REFILL_THRESHOLD_LITRES or more is a refill and
    starts a new interval; a smaller rise is noise and leaves the reference
    where it was, so the same litres are never counted twice.
    """
    allocated: DatedHistory = []
    reference: float | None = None
    since: datetime | None = None
    for moment, volume in sorted(samples, key=lambda sample: sample[0]):
        if reference is None or volume >= reference + IMPORT_REFILL_THRESHOLD_LITRES:
            reference, since = volume, moment
        elif volume < reference:
            allocated.extend(allocate_over_days(reference - volume, since, moment))
            reference, since = volume, moment
    return allocated


# --- seasonal forecast ------------------------------------------------------


def _year_angle(day: date) -> float:
    """Return where `day` falls in the annual cycle, in radians."""
    return 2 * math.pi * (day.timetuple().tm_yday - 1) / YEAR_DAYS


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Solve a small linear system by Gaussian elimination.

    Three unknowns do not justify numpy. Returns None for a singular system
    rather than a forecast built on a division by almost nothing.
    """
    size = len(vector)
    rows = [[*matrix[i], vector[i]] for i in range(size)]
    for col in range(size):
        pivot = max(range(col, size), key=lambda row: abs(rows[row][col]))
        if abs(rows[pivot][col]) < 1e-9:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for row in range(col + 1, size):
            factor = rows[row][col] / rows[col][col]
            for k in range(col, size + 1):
                rows[row][k] -= factor * rows[col][k]
    solution = [0.0] * size
    for row in reversed(range(size)):
        known = sum(rows[row][k] * solution[k] for k in range(row + 1, size))
        solution[row] = (rows[row][size] - known) / rows[row][row]
    return solution


@dataclass(frozen=True, slots=True)
class SeasonalModel:
    """Daily consumption as a mean plus one annual sine wave.

    burn(day) = mean + cos_term * cos(angle) + sin_term * sin(angle)

    which is the same curve as mean + amplitude * cos(angle - peak), written
    so that fitting it is ordinary linear least squares.
    """

    mean: float
    cos_term: float
    sin_term: float
    fit_days: int
    months_covered: int

    def expected(self, day: date) -> float:
        """Return the litres the model expects on `day`.

        Never negative: when the fitted swing is deeper than the mean, the
        trough is a tank burning nothing, not one refilling itself.
        """
        angle = _year_angle(day)
        burn = (
            self.mean
            + self.cos_term * math.cos(angle)
            + self.sin_term * math.sin(angle)
        )
        return max(0.0, burn)

    @property
    def amplitude(self) -> float:
        """Return how far the peak sits above the mean, in L/day."""
        return math.hypot(self.cos_term, self.sin_term)

    @property
    def peak(self) -> date:
        """Return the day of the (non-leap) year the model burns most on."""
        angle = math.atan2(self.sin_term, self.cos_term) % (2 * math.pi)
        offset = round(angle / (2 * math.pi) * YEAR_DAYS) % 365
        return date(2001, 1, 1) + timedelta(days=offset)


def fit_seasonal(totals: dict[str, float], now: datetime) -> SeasonalModel | None:
    """Fit the annual cycle to the complete days in `totals`.

    A sine wave fitted to six weeks of autumn can put the peak anywhere, so
    the fit is regularised towards PRIOR_AMPLITUDE_RATIO and
    PRIOR_PEAK_DAY_OF_YEAR: two extra equations saying "the swing is that
    share of the mean, peaking then", each weighted as PRIOR_WEIGHT_DAYS of
    evidence. With a few weeks of history the default shape is scaled to fit
    what the tank actually burns; with a year of it the tank's own shape wins.

    The prior is stated relative to the mean rather than in litres, so it
    holds for a cottage and a farmhouse alike.
    """
    today = now.date().isoformat()
    days = [
        (date.fromisoformat(day), litres)
        for day, litres in totals.items()
        if day < today
    ]
    if len(days) < SEASONAL_MIN_DAYS:
        return None

    peak_angle = 2 * math.pi * (PRIOR_PEAK_DAY_OF_YEAR - 1) / YEAR_DAYS
    prior_cos = PRIOR_AMPLITUDE_RATIO * math.cos(peak_angle)
    prior_sin = PRIOR_AMPLITUDE_RATIO * math.sin(peak_angle)
    weight = math.sqrt(PRIOR_WEIGHT_DAYS)

    design: list[tuple[list[float], float]] = [
        ([1.0, math.cos(angle), math.sin(angle)], litres)
        for angle, litres in ((_year_angle(day), litres) for day, litres in days)
    ]
    design.append(([-prior_cos * weight, weight, 0.0], 0.0))
    design.append(([-prior_sin * weight, 0.0, weight], 0.0))

    # Normal equations: (X^T X) b = X^T y.
    normal = [
        [sum(row[i] * row[j] for row, _ in design) for j in range(3)] for i in range(3)
    ]
    rhs = [sum(row[i] * litres for row, litres in design) for i in range(3)]
    solution = _solve(normal, rhs)
    if solution is None or solution[0] <= 0:
        return None

    mean, cos_term, sin_term = solution
    return SeasonalModel(
        mean=mean,
        cos_term=cos_term,
        sin_term=sin_term,
        fit_days=len(days),
        months_covered=len({day.month for day, _ in days}),
    )


def recent_anomaly(
    model: SeasonalModel,
    totals: dict[str, float],
    now: datetime,
    window: int = CONSUMPTION_ROLLING_DAYS,
) -> float:
    """Return how the last complete days compare with what the model expected.

    1.2 means the last week burnt 20% more than the season accounts for.
    Measured over the same days the rolling rate averages.
    """
    today = now.date().isoformat()
    recent = [(day, litres) for day, litres in totals.items() if day < today]
    recent = recent[-window:]
    expected = sum(model.expected(date.fromisoformat(day)) for day, _ in recent)
    if expected <= 0:
        return 1.0
    actual = sum(litres for _, litres in recent)
    return min(ANOMALY_MAX, max(ANOMALY_MIN, actual / expected))


@dataclass(frozen=True, slots=True)
class Forecast:
    """The seasonal model, nudged by how the tank has been running lately."""

    model: SeasonalModel
    anomaly: float
    today: date

    def daily(self, day: date) -> float:
        """Return the litres expected on `day`.

        The recent anomaly applies in full today and fades by half every
        ANOMALY_HALF_LIFE_DAYS, so a cold snap moves next week's forecast
        and barely touches next winter's.
        """
        ahead = max(0, (day - self.today).days)
        persistence = math.pow(0.5, ahead / ANOMALY_HALF_LIFE_DAYS)
        return self.model.expected(day) * (1 + (self.anomaly - 1) * persistence)

    def monthly(self, months: int = FORECAST_MONTHS) -> dict[str, float]:
        """Return the litres expected in each of the next `months` months.

        Whole calendar months, starting with the current one, so the figures
        sit beside the measured monthly totals.
        """
        result: dict[str, float] = {}
        year, month = self.today.year, self.today.month
        for _ in range(months):
            day = date(year, month, 1)
            litres = 0.0
            while day.month == month:
                litres += self.daily(day)
                day += timedelta(days=1)
            result[f"{year:04d}-{month:02d}"] = round(litres, 1)
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return result


def seasonal_forecast(totals: dict[str, float], now: datetime) -> Forecast | None:
    """Return the seasonal forecast, or None when there is too little history."""
    model = fit_seasonal(totals, now)
    if model is None:
        return None
    return Forecast(
        model=model, anomaly=recent_anomaly(model, totals, now), today=now.date()
    )


def days_until_empty_seasonal(
    volume_litres: int | None, outlook: Forecast, now: datetime
) -> float | None:
    """Walk the forecast forward until it has burnt what is in the tank.

    Today counts only for the part of it still to come. None when the tank
    outlasts the forecast horizon, which for a model that has learnt the
    tank burns nothing all summer is the honest answer.
    """
    if volume_litres is None:
        return None
    remaining = float(volume_litres)
    if remaining <= 0:
        return 0.0

    seconds_into_day = now.hour * 3600 + now.minute * 60 + now.second
    span = 1 - seconds_into_day / 86400
    elapsed = 0.0
    day = now.date()
    while elapsed < FORECAST_HORIZON_DAYS:
        burn = outlook.daily(day) * span
        if burn >= remaining:
            return round(elapsed + span * remaining / burn, 1)
        remaining -= burn
        elapsed += span
        span = 1.0
        day += timedelta(days=1)
    return None
