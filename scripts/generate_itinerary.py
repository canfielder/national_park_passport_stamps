"""Generate a trip itinerary for stamp collecting from parkstamps.org HTML files.

Usage:
    uv run python scripts/generate_itinerary.py <trip-folder>

Output:
    <trip-folder>/itinerary.html
"""

import html
import logging
import math
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from src.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

USERNAME = "CanfieldER"
SERIES_NEARBY_KM = 25.0

SERIES_CSV = PROJECT_ROOT / "data" / "manual_tracking" / "national_park_passport_stamp_series.csv"


# ── Data models ──────────────────────────────────────────────────────────────


@dataclass
class Stamp:
    """A single cancellation stamp available at a location."""

    stamp_id: str
    park: str
    stamp_type: str
    status: str
    tags: str
    stamp_text: str
    notes: str
    collected: bool
    collected_date: str


@dataclass
class Location:
    """A physical stamp station parsed from a parkstamps.org printer-friendly page."""

    location_id: str
    name: str
    website: str
    address: str
    gps: tuple[float, float]
    phone: str
    hours: str
    stamps: list[Stamp] = field(default_factory=list)


# ── HTML parsing ──────────────────────────────────────────────────────────────


def _strip_tags(text: str) -> str:
    """Remove HTML tags and decode entities from a string."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return " ".join(text.split())


def _extract_field(pattern: str, content: str, default: str = "") -> str:
    """Return first regex group match, stripped of HTML tags."""
    m = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
    return _strip_tags(m.group(1)).strip() if m else default


def parse_location_file(path: Path) -> Location:
    """Parse a parkstamps.org printer-friendly HTML file into a Location.

    Args:
        path: Path to the saved SingleFile HTML.

    Returns:
        Parsed Location with all stamps populated.
    """
    content = path.read_text(encoding="utf-8")

    # ── Location header ───────────────────────────────────────────────────────
    h1 = re.search(r"<h1>Location:\s*(\S+)\s*-\s*(.+?)</h1>", content)
    location_id = h1.group(1) if h1 else path.stem
    name = _strip_tags(h1.group(2)).strip() if h1 else path.stem

    def _header_field(label: str) -> str:
        m = re.search(
            rf"<strong>{label}:</strong><td>(.*?)</tr>",
            content,
            re.DOTALL | re.IGNORECASE,
        )
        return _strip_tags(m.group(1)).strip() if m else ""

    website = _header_field("Website")
    address = _header_field("Address")
    phone = _header_field("Phone")
    hours = _header_field("Hours")

    gps_raw = _header_field("GPS")
    try:
        lat_str, lon_str = gps_raw.split(",")
        gps: tuple[float, float] = (float(lat_str.strip()), float(lon_str.strip()))
    except (ValueError, AttributeError):
        gps = (0.0, 0.0)

    location = Location(
        location_id=location_id,
        name=name,
        website=website,
        address=address,
        gps=gps,
        phone=phone,
        hours=hours,
    )

    # ── Parse stamps ──────────────────────────────────────────────────────────
    park_pattern = re.compile(r"<div class=[\"']?park[\"']?>(.*?)</div>", re.DOTALL)
    stamp_pattern = re.compile(r"<table class=[\"']?stamp[\"']?>(.*?)</table>", re.DOTALL)

    current_park = ""
    pos = 0

    while pos < len(content):
        park_match = park_pattern.search(content, pos)
        stamp_match = stamp_pattern.search(content, pos)

        if not stamp_match:
            break

        # Advance current_park if there's a park div before the next stamp
        if park_match and park_match.start() < stamp_match.start():
            current_park = _strip_tags(park_match.group(1)).strip()
            pos = park_match.end()
            continue

        stamp_html = stamp_match.group(1)

        stamp_id = _extract_field(r"<strong>ID:</strong>\s*(\d+)", stamp_html)
        stamp_type = _extract_field(
            r"<strong>Stamp Type:</strong>\s*(.+?)\s*(?:<br>|<div)", stamp_html
        )
        status = _extract_field(
            r"<strong>Status:</strong>\s*(.+?)\s*(?:<br>|<div)", stamp_html
        )
        tags = _extract_field(
            r"<strong>Tags:</strong>\s*(.+?)\s*(?:<br>|<div)", stamp_html
        )

        # Stamp text: <hr> → " / " separator
        stamp_text_m = re.search(
            r"<div class=[\"']?stamp-text[\"']?>(.*?)</div>", stamp_html, re.DOTALL
        )
        if stamp_text_m:
            raw = re.sub(r"<hr[^>]*>", " / ", stamp_text_m.group(1))
            stamp_text = _strip_tags(raw).strip()
        else:
            stamp_text = ""

        notes = _extract_field(
            r'<div class=["\']?notes["\']?><strong>Notes:</strong>\s*(.+?)</div>',
            stamp_html,
        )

        # Collected: your-stamps-col td has a date if collected, empty otherwise
        your_col_m = re.search(
            r'<td class=["\']?your-stamps-col[^"\']*["\']?[^>]*>(.*?)</td>',
            stamp_html,
            re.DOTALL,
        )
        collected_date = ""
        if your_col_m:
            collected_date = _strip_tags(your_col_m.group(1)).strip()
        collected = bool(collected_date)

        location.stamps.append(
            Stamp(
                stamp_id=stamp_id,
                park=current_park,
                stamp_type=stamp_type,
                status=status,
                tags=tags,
                stamp_text=stamp_text,
                notes=notes,
                collected=collected,
                collected_date=collected_date,
            )
        )

        pos = stamp_match.end()

    return location


# ── Series cross-reference ────────────────────────────────────────────────────


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance in km between two GPS coordinates."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(
        math.radians(lat2)
    ) * math.sin(dlon / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def find_nearby_series_stamps(
    location: Location,
    df_series: pd.DataFrame,
    threshold_km: float = SERIES_NEARBY_KM,
) -> list[dict]:
    """Find uncollected passport series stamps near a cancellation location.

    Args:
        location: The cancellation station.
        df_series: Passport stamp series dataframe.
        threshold_km: Distance cutoff in km.

    Returns:
        List of nearby uncollected series stamp dicts, sorted by distance.
    """
    if location.gps == (0.0, 0.0):
        return []

    lat, lon = location.gps
    nearby = []

    for _, row in df_series.iterrows():
        if row["visited"] == "Yes":
            continue
        dist = _haversine_km(lat, lon, float(row["latitude"]), float(row["longitude"]))
        if dist <= threshold_km:
            nearby.append(
                {
                    "name": row["name"],
                    "year": int(row["year"]),
                    "region": row["region"],
                    "distance_km": round(dist, 1),
                }
            )

    return sorted(nearby, key=lambda x: x["distance_km"])


# ── Cross-location stamp index ────────────────────────────────────────────────


def build_stamp_location_index(
    locations: list[Location],
) -> dict[str, list[str]]:
    """Build a map of stamp_id → [location_ids] across all locations in the trip.

    Args:
        locations: All parsed locations for the trip.

    Returns:
        Dict mapping stamp ID to the list of location IDs that carry it.
        Only stamps appearing at more than one location are included.
    """
    index: dict[str, list[str]] = {}
    for loc in locations:
        for stamp in loc.stamps:
            index.setdefault(stamp.stamp_id, []).append(loc.location_id)
    return {sid: lids for sid, lids in index.items() if len(lids) > 1}


# ── HTML generation ───────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 15px;
    line-height: 1.5;
    color: #222;
    max-width: 800px;
    margin: 0 auto;
    padding: 16px;
    background: #f0f0f0;
}
h1 { font-size: 22px; margin-bottom: 2px; }
.generated { font-size: 12px; color: #888; margin-bottom: 20px; }
.location-card {
    background: white;
    border-radius: 8px;
    margin-bottom: 20px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.12);
}
.location-header { background: #2c5f2e; color: white; padding: 12px 16px; }
.location-id { font-size: 11px; opacity: 0.75; text-transform: uppercase; letter-spacing: 0.5px; }
.location-header h2 { font-size: 16px; margin: 4px 0 2px; }
.progress { font-size: 12px; opacity: 0.85; }
.location-meta {
    padding: 10px 16px;
    background: #f9f9f9;
    border-bottom: 1px solid #eee;
    font-size: 13px;
    display: flex;
    flex-direction: column;
    gap: 4px;
}
.location-meta a { color: #1a73e8; text-decoration: none; }
.series-alert {
    background: #fff8e1;
    border-left: 4px solid #f5a623;
    padding: 10px 16px;
    font-size: 13px;
    border-bottom: 1px solid #eee;
}
.series-alert ul { margin: 6px 0 0 18px; }
.series-alert li { margin-bottom: 2px; }
.park-header {
    background: #444;
    color: white;
    padding: 4px 16px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.4px;
}
.stamp-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 16px;
    border-bottom: 1px solid #f0f0f0;
}
.stamp-row:last-child { border-bottom: none; }
.stamp-collected { opacity: 0.4; }
.icon { font-size: 16px; flex-shrink: 0; margin-top: 1px; }
.check { color: #28a745; }
.uncheck { color: #dc3545; }
.stamp-info { flex: 1; min-width: 0; }
.stamp-name { font-weight: 500; font-size: 14px; }
.stamp-meta { font-size: 11px; color: #777; margin-top: 2px; }
.stamp-notes {
    background: #fff3cd;
    border-left: 3px solid #ffc107;
    padding: 4px 8px;
    margin-top: 6px;
    font-size: 12px;
    border-radius: 2px;
    color: #555;
}
.stamp-also-at {
    background: #e8f4fd;
    border-left: 3px solid #5bc0de;
    padding: 4px 8px;
    margin-top: 4px;
    font-size: 12px;
    border-radius: 2px;
    color: #555;
}
"""


def _render_location(
    loc: Location,
    series_nearby: list[dict],
    stamp_index: dict[str, list[str]],
    loc_names: dict[str, str],
) -> str:
    """Render a single location card as an HTML string.

    Args:
        loc: Parsed location.
        series_nearby: Uncollected passport series stamps near this location.
        stamp_index: Map of stamp_id → [location_ids] for stamps shared across
            multiple locations in this trip.
        loc_names: Map of location_id → location name for display.

    Returns:
        HTML string for the location card.
    """
    esc = html.escape
    n_collected = sum(1 for s in loc.stamps if s.collected)
    total = len(loc.stamps)
    progress = f"{n_collected} of {total} collected"

    parts: list[str] = [
        '<div class="location-card">',
        '  <div class="location-header">',
        f'    <div class="location-id">{esc(loc.location_id)}</div>',
        f"    <h2>{esc(loc.name)}</h2>",
        f'    <div class="progress">{progress}</div>',
        "  </div>",
        '  <div class="location-meta">',
    ]

    if loc.address:
        maps_url = f"https://maps.google.com/?q={loc.gps[0]},{loc.gps[1]}"
        parts.append(f'    <div>📍 <a href="{maps_url}">{esc(loc.address)}</a></div>')
    if loc.hours:
        parts.append(f"    <div>🕐 {esc(loc.hours)}</div>")
    if loc.phone:
        parts.append(f"    <div>📞 {esc(loc.phone)}</div>")
    if loc.website:
        parts.append(
            f'    <div>🌐 <a href="{esc(loc.website)}">{esc(loc.website)}</a></div>'
        )

    parts.append("  </div>")

    # Series cross-reference
    if series_nearby:
        parts += [
            '  <div class="series-alert">',
            "    <strong>📖 Nearby uncollected passport series stamps:</strong>",
            "    <ul>",
        ]
        for s in series_nearby:
            parts.append(
                f'      <li>{esc(s["name"])} ({s["year"]}) — {s["distance_km"]} km</li>'
            )
        parts += ["    </ul>", "  </div>"]

    # Stamps — grouped by park, uncollected first within each group
    park_order: list[str] = []
    for s in loc.stamps:
        if s.park not in park_order:
            park_order.append(s.park)

    stamps_by_park: dict[str, list[Stamp]] = {p: [] for p in park_order}
    for s in loc.stamps:
        stamps_by_park[s.park].append(s)

    parts.append('  <div class="stamps">')

    for park in park_order:
        park_stamps = stamps_by_park[park]
        uncollected = [s for s in park_stamps if not s.collected]
        collected = [s for s in park_stamps if s.collected]

        if park:
            parts.append(f'    <div class="park-header">{esc(park)}</div>')

        for s in uncollected + collected:
            row_class = "stamp-row stamp-collected" if s.collected else "stamp-row"
            icon_class = "icon check" if s.collected else "icon uncheck"
            icon = "✓" if s.collected else "○"

            meta_parts: list[str] = [esc(s.stamp_type)]
            if s.tags:
                meta_parts.append(esc(s.tags))
            if s.collected and s.collected_date:
                meta_parts.append(f"Collected {esc(s.collected_date)}")

            parts += [
                f'    <div class="{row_class}">',
                f'      <span class="{icon_class}">{icon}</span>',
                '      <div class="stamp-info">',
                f'        <div class="stamp-name">{esc(s.stamp_text or s.park)}</div>',
                f'        <div class="stamp-meta">{" · ".join(meta_parts)}</div>',
            ]

            if s.notes:
                parts.append(f'        <div class="stamp-notes">⚠️ {esc(s.notes)}</div>')

            # Flag stamps available at other locations in this trip
            if not s.collected and s.stamp_id in stamp_index:
                others = [
                    lid for lid in stamp_index[s.stamp_id] if lid != loc.location_id
                ]
                if others:
                    other_labels = ", ".join(
                        f"{esc(lid)} ({esc(loc_names.get(lid, lid))})"
                        for lid in others
                    )
                    parts.append(
                        f'        <div class="stamp-also-at">'
                        f"🔁 Also at: {other_labels}</div>"
                    )

            parts += ["      </div>", "    </div>"]

    parts += ["  </div>", "</div>"]
    return "\n".join(parts)


def generate_html(
    locations: list[Location],
    series_refs: dict[str, list[dict]],
    trip_name: str,
) -> str:
    """Generate the full itinerary HTML document.

    Args:
        locations: Parsed locations, already sorted.
        series_refs: Dict mapping location_id to nearby uncollected series stamps.
        trip_name: Used as the page title.

    Returns:
        Complete HTML string.
    """
    today = date.today().isoformat()
    stamp_index = build_stamp_location_index(locations)
    loc_names = {loc.location_id: loc.name for loc in locations}
    cards = "\n".join(
        _render_location(loc, series_refs.get(loc.location_id, []), stamp_index, loc_names)
        for loc in locations
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stamp Itinerary — {html.escape(trip_name)}</title>
  <style>{_CSS}</style>
</head>
<body>
  <h1>Stamp Itinerary</h1>
  <div class="generated">{html.escape(trip_name)} · Generated {today}</div>
  {cards}
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    """Parse trip HTML files and write a stamp collecting itinerary."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) < 2:
        logger.error("Usage: generate_itinerary.py <trip-folder>")
        sys.exit(1)

    trip_dir = Path(sys.argv[1])
    if not trip_dir.is_dir():
        logger.error("Not a directory: %s", trip_dir)
        sys.exit(1)

    # ── Load passport series stamps ───────────────────────────────────────────
    df_series = pd.read_csv(SERIES_CSV)

    # ── Parse location HTML files ─────────────────────────────────────────────
    html_files = sorted(
        f for f in trip_dir.glob("*.html") if f.name != "itinerary.html"
    )
    if not html_files:
        logger.error("No HTML files found in %s", trip_dir)
        sys.exit(1)

    locations: list[Location] = []
    for f in html_files:
        logger.info("Parsing %s", f.name)
        locations.append(parse_location_file(f))

    locations.sort(key=lambda loc: loc.name)

    # ── Cross-reference series stamps ─────────────────────────────────────────
    series_refs: dict[str, list[dict]] = {}
    for loc in locations:
        nearby = find_nearby_series_stamps(loc, df_series)
        if nearby:
            series_refs[loc.location_id] = nearby
            logger.info(
                "  %s: %s nearby uncollected series stamp(s)",
                loc.location_id,
                f"{len(nearby):,}",
            )

    # ── Write itinerary ───────────────────────────────────────────────────────
    output = generate_html(locations, series_refs, trip_dir.name)
    out_path = trip_dir / "itinerary.html"
    out_path.write_text(output, encoding="utf-8")
    logger.info("Itinerary written to %s", out_path)


if __name__ == "__main__":
    main()
