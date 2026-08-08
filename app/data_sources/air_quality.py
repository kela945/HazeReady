"""Live data clients for data.gov.sg, with fixtures for offline reproducibility.

Caching: responses are cached for `upstream_cache_ttl_s` (default 300s).
Readings are published hourly, so a 5-minute cache cannot serve a value that is
meaningfully staler than the endpoint would return, and it keeps an evaluation
run from issuing 180 identical requests.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.agent.tools.bands import resolve_psi_band, worse_band
from app.models import AirQualityReading, Forecast, HotspotSummary, Region

SGT = timezone(timedelta(hours=8))

_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: int) -> Any | None:
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    return None


def _store(key: str, value: Any) -> None:
    _cache[key] = (time.time(), value)


def clear_cache() -> None:
    _cache.clear()


class AirQualityClient:
    def __init__(
        self,
        psi_url: str,
        pm25_url: str,
        fixtures_dir: Path,
        offline: bool = False,
        timeout_s: float = 12.0,
        cache_ttl_s: int = 300,
    ) -> None:
        self.psi_url = psi_url
        self.pm25_url = pm25_url
        self.fixtures_dir = fixtures_dir
        self.offline = offline
        self.timeout_s = timeout_s
        self.cache_ttl_s = cache_ttl_s
        self.last_success: dict[str, str] = {}
        self.last_error: dict[str, str] = {}

    # -- fixtures -----------------------------------------------------------

    def _fixture(self, name: str) -> dict:
        path = self.fixtures_dir / name
        return json.loads(path.read_text(encoding="utf-8"))

    # -- fetching -----------------------------------------------------------

    async def _get(self, url: str, fixture_name: str, label: str) -> tuple[dict, str]:
        """Returns (payload, source). Falls back to the fixture on any upstream
        failure, and labels the result so the UI can say which it is showing."""
        if self.offline:
            return self._fixture(fixture_name), "fixture"

        cached = _cached(url, self.cache_ttl_s)
        if cached is not None:
            return cached, "live"

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                payload = resp.json()
            _store(url, payload)
            self.last_success[label] = datetime.now(SGT).isoformat()
            self.last_error.pop(label, None)
            return payload, "live"
        except Exception as exc:
            self.last_error[label] = f"{type(exc).__name__}: {exc}"
            return self._fixture(fixture_name), "fixture"

    # -- public API ---------------------------------------------------------

    async def get_current_air_quality(self, region: Region | None = None) -> AirQualityReading:
        region = region or Region.national
        psi_payload, psi_src = await self._get(
            self.psi_url, "psi_current.json", "data.gov.sg/psi"
        )
        pm_payload, _ = await self._get(self.pm25_url, "pm25_current.json", "data.gov.sg/pm25")

        item = psi_payload["items"][0]
        psi_readings = item["readings"]["psi_twenty_four_hourly"]
        psi_value = psi_readings.get(region.value)
        if psi_value is None:
            # The PM2.5 endpoint has no national key, and some payloads omit it
            # on PSI too. The worst region is the defensible substitute: taking
            # a lower figure would bias toward permission.
            psi_value = max(psi_readings.values())

        pm_item = pm_payload["items"][0]
        pm_readings = pm_item["readings"]["pm25_one_hourly"]
        pm_value = pm_readings.get(region.value)
        if pm_value is None:
            pm_value = max(pm_readings.values())

        reading_ts = datetime.fromisoformat(item["timestamp"])
        now = datetime.now(reading_ts.tzinfo or SGT)
        staleness = max(0, int((now - reading_ts).total_seconds()))

        return AirQualityReading(
            region=region,
            psi_24h=int(psi_value),
            pm25_1h=int(pm_value),
            reading_timestamp=reading_ts,
            fetched_at=now,
            staleness_seconds=staleness,
            source="fixture" if psi_src == "fixture" else "live",
            source_url=self.psi_url,
            note=(
                "Served from committed fixture."
                if psi_src == "fixture"
                else "Live reading from data.gov.sg."
            ),
        )

    async def get_air_quality_forecast(
        self, horizon_hours: int = 24, region: Region | None = None
    ) -> Forecast:
        """NEA's published forecast is a range with band language. data.gov.sg
        does not expose that bulletin as a structured endpoint, so this method
        derives a range around the current reading rather than pretending to
        read a forecast product.

        This is a stated approximation, not a forecast model. It is labelled
        `derived` in the output and in the UI, and the README says so. The
        purpose is to exercise the range-based decision path honestly; a system
        that reported a fabricated point forecast would be worse than one that
        says where its range came from.
        """
        reading = await self.get_current_air_quality(region)
        current = reading.psi_24h or 0
        # +/- 20% band, minimum +/- 10 index points, reflecting the spread seen
        # in published NEA bulletins (e.g. a reported 66-120 range).
        delta = max(10, int(round(current * 0.2)))
        low = max(0, current - delta)
        high = current + delta

        band_low = resolve_psi_band(low).band
        band_high = resolve_psi_band(high).band
        return Forecast(
            horizon_hours=horizon_hours,
            psi_low=low,
            psi_high=high,
            band_low=band_low,
            band_high=band_high,
            straddles_boundary=band_low != band_high,
            issued_at=datetime.now(SGT),
            source="derived",
            note=(
                "Derived range around the current 24-hour PSI, not an NEA forecast "
                "product. NEA publishes its forecast as a range; plan against the "
                "worst band the range reaches."
            ),
        )

    async def get_psi_history(self, hours: int = 24) -> dict:
        """Hourly 24-hour PSI per region for the trailing `hours`.

        data.gov.sg serves a whole day per request, so a 72-hour window needs
        three calls. Offline, a committed 3-day capture is replayed and the most
        recent `hours` are returned, so the map has a real shape rather than a
        flat line.
        """
        import datetime as _dt

        series: list[dict] = []
        if self.offline:
            fixture = self._fixture("psi_history.json")
            for day in sorted(fixture["days"]):
                series.extend(fixture["days"][day])
        else:
            today = _dt.datetime.now(SGT).date()
            days = 1 if hours <= 24 else (hours // 24) + 1
            for back in range(days - 1, -1, -1):
                day = (today - _dt.timedelta(days=back)).isoformat()
                try:
                    async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                        resp = await client.get(self.psi_url, params={"date": day})
                        resp.raise_for_status()
                        payload = resp.json()
                    series.extend(
                        {"t": it["timestamp"], "psi": it["readings"]["psi_twenty_four_hourly"]}
                        for it in payload.get("items", [])
                    )
                except Exception:
                    # A missing day degrades the trend line; it does not fail
                    # the request. The UI shows whatever window it received.
                    continue
            if not series:
                fixture = self._fixture("psi_history.json")
                for day in sorted(fixture["days"]):
                    series.extend(fixture["days"][day])

        series.sort(key=lambda r: r["t"])
        series = series[-hours:]
        regions = ["north", "south", "east", "west", "central"]
        return {
            "timestamps": [r["t"] for r in series],
            "regions": {reg: [r["psi"].get(reg) for r in series] for reg in regions},
            "source": "fixture" if self.offline else "live",
            "hours": len(series),
        }

    async def get_regional_hotspots(
        self, days: int = 1, bbox: tuple[float, float, float, float] = (95.0, -6.0, 119.0, 7.0)
    ) -> HotspotSummary:
        """NASA FIRMS requires an API key. Without one this returns an explicit
        `unavailable` result rather than a number, because a fabricated hotspot
        count would be indistinguishable from a real one in the UI."""
        fixture = self.fixtures_dir / "hotspots.json"
        if fixture.exists():
            data = json.loads(fixture.read_text(encoding="utf-8"))
            return HotspotSummary(
                days=days,
                count=int(data.get("count", 0)),
                bbox=bbox,
                source="fixture",
            )
        return HotspotSummary(days=days, count=0, bbox=bbox, source="unavailable")


def worst_band_in_forecast(forecast: Forecast):
    return worse_band(forecast.band_low, forecast.band_high)
