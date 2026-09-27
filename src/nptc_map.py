"""Parse the National Parks Travelers Club (NPTC) master map KML export.

The export (NPTCMasterMap_MM-DD-YYYY.kml, downloaded from parkstamps.org) holds
every stamping location with its stamps, and a checkmark on each stamp the
account owner has collected. It has no collection dates.
"""

import html
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.paths import PROJECT_ROOT

NPTC_EXPORT_DIR = PROJECT_ROOT / "data" / "raw" / "nptc"

KML_NS = {"k": "http://www.opengis.net/kml/2.2"}

# Each stamp is a table row: collected cell, image cell, then a details table
STAMP_ROW_RE = re.compile(
    r"<tr style='[^']*'><td>(?P<collected>.*?)</td><td><img.*?"
    r"<strong>Id:</strong>\s*(?P<id>\d+);\s*<strong>Status:</strong>\s*(?P<status>.*?)</td>.*?"
    r"<strong>Type:</strong>\s*(?P<type>.*?)\s*</td>.*?"
    r"<strong>Text:</strong>\s*(?P<text>.*?)</td>",
    re.S,
)


@dataclass(frozen=True)
class NptcStamp:
    """A single cancellation stamp listed at a stamping location."""

    stamp_id: str
    stamp_type: str
    status: str
    text: str
    collected: bool


@dataclass
class NptcLocation:
    """A stamping location (a physical desk or station) from the master map."""

    location_id: str
    name: str
    region: str
    latitude: float
    longitude: float
    stamps: list[NptcStamp] = field(default_factory=list)


def _clean_text(raw: str) -> str:
    """Flatten stamp text HTML: line breaks become ' / ', other tags are dropped."""
    text = re.sub(r"<br\s*/?>", " / ", raw, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip(" /")


def _parse_placemark(placemark: ET.Element, region: str) -> NptcLocation:
    """Build a location, with its stamps, from one Placemark element."""
    description = placemark.findtext("k:description", default="", namespaces=KML_NS)
    id_match = re.search(r"<b>MDB Id</b></td><td>(.*?)</td>", description)

    # Coordinates are "lon,lat,alt"
    coords = placemark.findtext(".//k:coordinates", namespaces=KML_NS).strip()
    lon, lat = (float(v) for v in coords.split(",")[:2])

    stamps = [
        NptcStamp(
            stamp_id=m["id"],
            stamp_type=m["type"].strip(),
            status=m["status"].strip(),
            text=_clean_text(m["text"]),
            collected="green_check" in m["collected"],
        )
        for m in STAMP_ROW_RE.finditer(description)
    ]
    return NptcLocation(
        location_id=id_match.group(1).strip() if id_match else "",
        name=placemark.findtext("k:name", default="", namespaces=KML_NS).strip(),
        region=region,
        latitude=lat,
        longitude=lon,
        stamps=stamps,
    )


def load_stamping_locations(kml_path: Path) -> list[NptcLocation]:
    """Load every stamping location from a master map export.

    The "Places of Interest" folder (sites with no stamps) is skipped.

    Args:
        kml_path: Path to an NPTCMasterMap KML export.

    Returns:
        Stamping locations, each with its stamps and collected flags.
    """
    root = ET.parse(kml_path).getroot()
    stamping = next(
        folder
        for folder in root.iter(f"{{{KML_NS['k']}}}Folder")
        if folder.findtext("k:name", namespaces=KML_NS) == "Stamping Locations"
    )

    locations = []
    # Stamping Locations is split into one sub-folder per NPS region
    for region_folder in stamping.findall("k:Folder", KML_NS):
        region = region_folder.findtext("k:name", default="", namespaces=KML_NS)
        for placemark in region_folder.findall(".//k:Placemark", KML_NS):
            locations.append(_parse_placemark(placemark, region))
    return locations


def _export_date(path: Path) -> datetime:
    """Parse the MM-DD-YYYY date from an export file name."""
    return datetime.strptime(path.stem.rsplit("_", 1)[-1], "%m-%d-%Y")


def latest_export(export_dir: Path = NPTC_EXPORT_DIR) -> Path:
    """Return the most recent NPTCMasterMap export in a directory.

    Raises:
        FileNotFoundError: If the directory holds no exports.
    """
    exports = sorted(export_dir.glob("NPTCMasterMap_*.kml"), key=_export_date)
    if not exports:
        raise FileNotFoundError(f"No NPTCMasterMap_*.kml exports in {export_dir}")
    return exports[-1]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))
