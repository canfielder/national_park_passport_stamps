"""Log new stamp photos into the cancellation stamp log CSV.

Scans data/stamp_photos/ for photos not yet in the log and adds one row per
photo with a best-guess collection date (see resolve_collection_date). Fill in
stamp_id by hand, then re-run: rows with a stamp_id get their stamp_text, and
their location when the stamp exists at only one NPTC stamping location, filled
from the latest master map export.

Photo GPS is deliberately ignored. Stamps are usually photographed at the end
of the day or back home, so the GPS points at a hotel or house, not the desk.

Usage:
    uv run python -m scripts.log_stamp_photos
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from PIL import ExifTags, Image
from pillow_heif import register_heif_opener

from src.nptc_map import NptcLocation, latest_export, load_stamping_locations
from src.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

PHOTO_DIR = PROJECT_ROOT / "data" / "stamp_photos"
LOG_CSV = PROJECT_ROOT / "data" / "manual_tracking" / "cancellation_stamp_log.csv"

PHOTO_SUFFIXES = {".heic", ".heif", ".jpg", ".jpeg", ".png"}

# Note left on rows logged from a raw page photo, cleared once cropped
CROP_NOTE_RE = re.compile(r"[;,]?\s*raw page photo[;,]\s*crop out this stamp", re.I)

# Cropped copies: "gettysburg_cropped", "20200823_202017 - cropped"
CROPPED_RE = re.compile(r"[\s_-]*cropped$", re.I)

LOG_COLUMNS = [
    "photo_file",
    "date_collected",
    "date_source",
    "stamp_id",
    "stamp_text",
    "retired",
    "location_id",
    "location_name",
    "location_source",
    "stamped_elsewhere",
    "mail_type",
    "needs_crop",
    "uploaded_to_nptc",
    "notes",
    "original_file",
]

# EXIF tag ids
TAG_DATETIME = 306
TAG_DATETIME_ORIGINAL = 36867

# Trip folders start with a date or date range: "20260918-20260919_new-york-city"
# (the convention), and older styles like "20170918 - Gettysburg",
# "20240614_24 - Pacific Northwest" (end day), "20250131-0202 - Arkansas"
# (end month+day), or "2026-09-18__nyc"
TRIP_DATE_RE = re.compile(r"^(\d{4}-?\d{2}-?\d{2})(?:[_-](\d{8}|\d{4}|\d{2}))?(?!\d)")

# Naming convention for stamp photos: YYYYMMDD__<location>__<stamp_id>[_n], plus
# YYYYMMDD__<location>__unknown_<desc> for unidentified stamps,
# YYYYMMDD__<location>__personal_<desc> for personal stamps (no NPTC id), and
# YYYYMMDD_page_<n> for full-page shots. The older YYYYMMDD_<stamp_id> (no
# location) still parses.
FILE_NAME_RE = re.compile(
    r"^\d{8}(?:__(?P<location>[a-z0-9-]+)__|__|_)(?P<stamp>\d{5}|unknown|personal|page)(?:_|$)",
    re.I,
)

# Location slot for a mailed stamp whose mailing station is unknown, and for any
# other unknown location
MAIL_LOCATION = "mail"

# NPTC mail codes, also used as the location slot of a mailed stamp's name:
#   ml1  mail - same year as the visit
#   ml2  mail - not the same year as the visit
#   ml3  mail - other (not tied to a visit)
# "mail" marks a mailed stamp whose code isn't decided yet
MAIL_CODES = {"ml1", "ml2", "ml3"}
MAIL_TYPES = MAIL_CODES | {MAIL_LOCATION}

# stamp_id for a personal stamp: logged on NPTC as a personal stamp, which
# carries no NPTC stamp id (e.g. a state park that isn't in the master map)
PERSONAL = "personal"
UNKNOWN_LOCATION = "unknown"

# Hand-written dates at the start of a file name: "2024-06-16_...", "20260124__...",
# or "180520 - ..." (YYMMDD). Camera names like "20201021_125555" and screenshot
# names like "2019-12-25 16_12_04" are excluded: they are when the photo was
# taken, not when the stamp was collected.
NAME_DATE_RE = re.compile(
    r"^(?:misc_)?(\d{4}-\d{2}-\d{2}|\d{8}|\d{6})(?!\d)(?![ _]\d{2}[_:]?\d{2}[_:]?\d{2})",
    re.I,
)


def read_photo_taken(path: Path) -> datetime | None:
    """Read a photo's EXIF capture time, if present."""
    with Image.open(path) as img:
        exif = img.getexif()
    # DateTimeOriginal is the capture time; DateTime can be an edit time
    raw_dt = exif.get_ifd(ExifTags.IFD.Exif).get(TAG_DATETIME_ORIGINAL) or exif.get(
        TAG_DATETIME
    )
    try:
        return datetime.strptime(raw_dt, "%Y:%m:%d %H:%M:%S") if raw_dt else None
    except ValueError:
        return None


def _parse_compact_date(raw: str) -> date | None:
    """Parse YYYY-MM-DD, YYYYMMDD, or YYMMDD, returning None if not a real date."""
    digits = raw.replace("-", "")
    fmt = "%Y%m%d" if len(digits) == 8 else "%y%m%d"
    try:
        return datetime.strptime(digits, fmt).date()
    except ValueError:
        return None


def parse_trip_range(folder_name: str) -> tuple[date, date] | None:
    """Parse the date range from a trip folder name.

    Args:
        folder_name: e.g. "20240614_24 - Pacific Northwest".

    Returns:
        Start and end dates (equal for one-day trips), or None if the name has
        no leading date.
    """
    m = TRIP_DATE_RE.match(folder_name)
    start = _parse_compact_date(m.group(1)) if m else None
    if start is None:
        return None

    end = start
    if m.group(2):
        # Eight digits are a full end date, four the end month and day, two the
        # end day
        end_raw = m.group(2)
        if len(end_raw) == 8:
            end = _parse_compact_date(end_raw) or start
            return start, max(start, end)
        if len(end_raw) == 4:
            month, day = int(end_raw[:2]), int(end_raw[2:])
        else:
            month, day = start.month, int(end_raw)
        try:
            end = date(start.year, month, day)
        except ValueError:
            end = start
    return start, max(start, end)


def parse_name_date(file_stem: str) -> date | None:
    """Parse a hand-written collection date from the start of a file name."""
    m = NAME_DATE_RE.match(file_stem)
    return _parse_compact_date(m.group(1)) if m else None


@dataclass(frozen=True)
class CollectionDate:
    """Best-guess collection date for a photo and where it came from."""

    value: date | None
    source: str


def resolve_collection_date(photo_file: str, taken: datetime | None) -> CollectionDate:
    """Pick the most trustworthy collection date for a photo.

    Photos are often taken at home, sometimes years after a trip, so the EXIF
    date is only trusted when it falls within the trip folder's date range.

    Priority:
        1. A date written at the start of the file name ("filename")
        2. A dated subfolder inside the trip folder, innermost first, e.g.
           "2026-04-21/" or "190516 - John Day/" ("subfolder")
        3. The EXIF date, if it falls within the trip folder's range ("photo")
        4. The trip folder's start date ("trip_start", approximate)
        5. The EXIF date with nothing to check it against ("photo_unverified")

    Args:
        photo_file: Photo path relative to the photo folder; the first path
            component is the trip folder.
        taken: EXIF capture time, if present.

    Returns:
        The chosen date and its source.
    """
    parts = Path(photo_file).parts
    trip = parse_trip_range(parts[0]) if len(parts) > 1 else None
    name_date = parse_name_date(Path(photo_file).stem)
    taken_date = taken.date() if taken else None

    # Folders between the trip folder and the file, innermost first
    subfolder_dates = (parse_name_date(folder) for folder in reversed(parts[1:-1]))
    subfolder_date = next((d for d in subfolder_dates if d), None)

    if name_date:
        return CollectionDate(name_date, "filename")
    if subfolder_date:
        return CollectionDate(subfolder_date, "subfolder")
    if taken_date and trip and trip[0] <= taken_date <= trip[1]:
        return CollectionDate(taken_date, "photo")
    if trip:
        return CollectionDate(trip[0], "trip_start")
    if taken_date:
        return CollectionDate(taken_date, "photo_unverified")
    return CollectionDate(None, "")


def load_log() -> pd.DataFrame:
    """Load the log CSV, or an empty frame if it doesn't exist yet."""
    if not LOG_CSV.exists():
        return pd.DataFrame(columns=LOG_COLUMNS)
    # Read as strings: stamp ids are zero-padded ("03562")
    df_log = pd.read_csv(LOG_CSV, dtype=str, keep_default_na=False)
    # by_mail (Yes/blank) was replaced by mail_type; Yes becomes "mail"
    if "by_mail" in df_log.columns and "mail_type" not in df_log.columns:
        df_log["mail_type"] = df_log["by_mail"].map({"Yes": MAIL_LOCATION}).fillna("")
    # Columns added after a log was started come in blank
    for col in LOG_COLUMNS:
        if col not in df_log.columns:
            df_log[col] = ""
    return df_log


def _crop_base(stem: str) -> str | None:
    """Return the original's stem if this is a cropped copy, else None."""
    m = CROPPED_RE.search(stem)
    return stem[: m.start()] if m else None


def _is_superseded(photo: Path, cropped_bases: set[tuple[Path, str]]) -> bool:
    """Whether a cropped copy exists for this photo, so the original is skipped.

    Covers both habits: "X_cropped.jpg" / "X - cropped.jpg" saved next to
    "X.jpg", and a "raw/" folder with a "cropped/" folder beside it.
    """
    if (photo.parent, photo.stem) in cropped_bases:
        return True
    return any(
        folder.name.lower() == "raw" and (folder.parent / "cropped").is_dir()
        for folder in photo.parents
    )


def _find_new_photos(df_log: pd.DataFrame, photo_dir: Path) -> list[Path]:
    """List photos under the photo folder that have no row in the log yet.

    Originals that have a cropped copy are left out; the cropped copy is logged.
    """
    logged = set(df_log["photo_file"])
    photos = [p for p in photo_dir.rglob("*") if p.suffix.lower() in PHOTO_SUFFIXES]
    cropped_bases = {
        (p.parent, base) for p in photos if (base := _crop_base(p.stem)) is not None
    }
    return sorted(
        p
        for p in photos
        if not _is_superseded(p, cropped_bases)
        and p.relative_to(photo_dir).as_posix() not in logged
    )


def build_row(photo: Path, photo_dir: Path) -> dict[str, str]:
    """Build a log row for a new photo, with its best-guess collection date."""
    photo_file = photo.relative_to(photo_dir).as_posix()
    collected = resolve_collection_date(photo_file, read_photo_taken(photo))
    row = dict.fromkeys(LOG_COLUMNS, "")
    row["photo_file"] = photo_file
    row["original_file"] = photo_file
    row["date_collected"] = collected.value.isoformat() if collected.value else ""
    row["date_source"] = collected.source
    row["uploaded_to_nptc"] = "No"

    # Photos named by the convention carry their stamp id
    id_match = FILE_NAME_RE.match(photo.stem)
    if id_match:
        tag = id_match.group("stamp").lower()
        row["stamp_id"] = {"page": "none", "unknown": ""}.get(tag, tag)
    return row


def _adopt_crop(df_log: pd.DataFrame, photo: Path) -> bool:
    """Point a needs_crop row at a new cropped photo named for its stamp.

    A stamp first logged from a raw page photo is flagged needs_crop. When a
    crop named for that stamp id appears in the same trip folder, or with the
    row's collection date (a page can hold stamps from several trips), the
    existing row (with its notes) moves to the crop instead of a new row being
    added.

    Returns:
        True if an existing row adopted the photo.
    """
    id_match = FILE_NAME_RE.match(photo.stem)
    if not id_match or not id_match.group("stamp").isdigit():
        return False
    photo_file = photo.relative_to(PHOTO_DIR).as_posix()
    trip = Path(photo_file).parts[0]
    name_date = f"{photo.stem[:4]}-{photo.stem[4:6]}-{photo.stem[6:8]}"
    same_trip = df_log["photo_file"].map(lambda f: Path(f).parts[0]) == trip
    candidates = df_log.index[
        (df_log["stamp_id"] == id_match.group("stamp"))
        & (df_log["needs_crop"] == "Yes")
        & (same_trip | (df_log["date_collected"] == name_date))
    ]
    if len(candidates) != 1:
        return False
    idx = candidates[0]
    df_log.loc[idx, ["photo_file", "needs_crop"]] = [photo_file, ""]
    df_log.loc[idx, "notes"] = CROP_NOTE_RE.sub("", df_log.at[idx, "notes"]).strip(
        "; ,"
    )
    logger.info("%s → cropped copy adopted by its needs_crop row", photo_file)
    return True


def _fill_locations(
    df_log: pd.DataFrame,
    stations_by_id: dict[str, list[NptcLocation]],
) -> None:
    """Fill location_id (the station where each stamp was collected).

    Only rows with a blank location_source are touched, so hand entries
    (manual / file_name) and deliberate blanks are never overwritten.

    Sources, most to least certain:
        only_station  The master map lists the stamp at a single station.
        same_day      The stamp's stations include exactly one station where
                      another stamp was collected the same day.

    Stamps received by mail (mail_type set) only get only_station: nothing
    was visited that day, so same-day guesses don't apply. A blank location_id
    on a mailed row means the mailing station is unknown.

    The map is a current snapshot: stamps move between desks, so either
    source is a best guess for older collections.
    """
    names = {
        loc.location_id: loc.name for locs in stations_by_id.values() for loc in locs
    }

    def _set(idx: int, location_id: str, source: str) -> None:
        df_log.loc[idx, ["location_id", "location_name", "location_source"]] = [
            location_id,
            names.get(location_id, ""),
            source,
        ]

    # A same-day guess made before a row was marked as mailed no longer holds
    stale = (df_log["mail_type"] != "") & (df_log["location_source"] == "same_day")
    df_log.loc[stale, ["location_id", "location_name", "location_source"]] = ""

    # Stamps applied away from their own station can't be placed from the map
    open_rows = (
        (df_log["location_source"] == "")
        & df_log["stamp_id"].str.isdigit()
        & (df_log["stamped_elsewhere"] != "Yes")
    )

    for idx in df_log.index[open_rows]:
        stations = stations_by_id.get(df_log.at[idx, "stamp_id"], [])
        if len(stations) == 1:
            _set(idx, stations[0].location_id, "only_station")

    # Stations visited each day, excluding other same-day guesses. Mailed
    # stamps don't count: their station wasn't visited on that date.
    mailed = df_log["mail_type"] != ""
    placed = df_log[
        (df_log["location_id"] != "")
        & (df_log["location_source"] != "same_day")
        & ~mailed
    ]
    stations_by_day = placed.groupby("date_collected")["location_id"].agg(set)

    for idx in df_log.index[open_rows & ~mailed & (df_log["location_source"] == "")]:
        candidates = {
            loc.location_id
            for loc in stations_by_id.get(df_log.at[idx, "stamp_id"], [])
        }
        same_day = candidates & stations_by_day.get(
            df_log.at[idx, "date_collected"], set()
        )
        if len(same_day) == 1:
            _set(idx, same_day.pop(), "same_day")

    # Fill names for ids entered by hand
    no_name = (df_log["location_id"] != "") & (df_log["location_name"] == "")
    df_log.loc[no_name, "location_name"] = (
        df_log.loc[no_name, "location_id"].map(names).fillna("")
    )


def _check_stamped_elsewhere(
    df_log: pd.DataFrame,
    stations_by_id: dict[str, list[NptcLocation]],
) -> None:
    """Warn where stamped_elsewhere disagrees with the stamp's own stations.

    The map is a current snapshot, so rows it can't judge are skipped: retired
    stations, and manual rows (confirmed by hand, even if the stamp has since
    moved).
    """
    map_stations = {loc.location_id for locs in stations_by_id.values() for loc in locs}
    for _, row in df_log[df_log["location_id"] != ""].iterrows():
        stations = {loc.location_id for loc in stations_by_id.get(row["stamp_id"], [])}
        if not stations:
            continue  # retired or unidentified: nothing to compare against
        if row["location_id"] not in map_stations:
            continue  # station since retired
        at_home = row["location_id"] in stations
        if row["location_source"] == "manual" and not at_home:
            continue  # confirmed by hand; the stamp may have moved since
        if row["stamped_elsewhere"] == "Yes" and at_home:
            logger.warning(
                "%s → stamped_elsewhere is Yes, but %s lists stamp %s",
                row["photo_file"],
                row["location_id"],
                row["stamp_id"],
            )
        elif row["stamped_elsewhere"] != "Yes" and not at_home:
            logger.warning(
                "%s → collected at %s, which doesn't list stamp %s "
                "(stamped elsewhere, or the stamp moved?)",
                row["photo_file"],
                row["location_id"],
                row["stamp_id"],
            )


def _fill_from_map(df_log: pd.DataFrame, locations: list[NptcLocation]) -> int:
    """Fill stamp_text, retired, and collected-at locations for rows with a stamp_id.

    retired is recomputed every run: Yes for a stamp id with no Active listing
    in the master map. Newer exports list retired stamps with a status
    ("Retired", "Retired at this Location"); older ones left them out, so a
    stamp missing from the map counts as retired too. Stations come from
    every listing, retired ones included, since a stamp may have been
    collected where it has since been retired.

    Returns:
        Number of rows that gained stamp text.
    """
    text_by_id: dict[str, str] = {}
    stations_by_id: dict[str, list[NptcLocation]] = {}
    active_ids: set[str] = set()
    for loc in locations:
        for s in loc.stamps:
            text_by_id[s.stamp_id] = s.text
            stations_by_id.setdefault(s.stamp_id, []).append(loc)
            # Older exports have no status: everything listed was active
            if s.status in ("Active", ""):
                active_ids.add(s.stamp_id)

    # Pad ids typed without leading zeros (e.g. 640 → 00640)
    df_log["stamp_id"] = (
        df_log["stamp_id"]
        .str.strip()
        .map(lambda sid: sid.zfill(5) if sid.isdigit() else sid)
    )

    needs_text = (df_log["stamp_id"] != "") & (df_log["stamp_text"] == "")
    df_log.loc[needs_text, "stamp_text"] = (
        df_log.loc[needs_text, "stamp_id"].map(text_by_id).fillna("")
    )

    # Derived, never hand-edited: a stamp can be retired after it was collected
    is_id = df_log["stamp_id"].str.isdigit()
    df_log["retired"] = ""
    df_log.loc[is_id & ~df_log["stamp_id"].isin(active_ids), "retired"] = "Yes"

    _fill_locations(df_log, stations_by_id)
    _check_stamped_elsewhere(df_log, stations_by_id)
    return int((needs_text & (df_log["stamp_text"] != "")).sum())


def _match_key(file_name: str) -> str:
    """File name without its location slot, so a location edit still matches."""
    return re.sub(r"^(\d{8})__[a-z0-9-]+__", r"\1_", file_name.lower())


def _name_parts(photo_file: str) -> tuple[str, str]:
    """Split a photo path into (name date, location slot)."""
    path = Path(photo_file)
    m = FILE_NAME_RE.match(path.stem)
    slot = (m.group("location") or "").lower() if m else ""
    return path.stem[:8], slot


def _pair_leftovers(missing: list[str], new: list[str]) -> dict[str, str]:
    """Pair missing photos with unlogged ones after a stamp id edit in the name.

    Within each name date, a single missing photo and a single new photo are
    paired. Where there are several, each location slot that leaves exactly
    one of each is paired. What's left is paired across dates when exactly one
    of each carries the same stamp id (a date edited in the name). Trip
    folders are ignored, since they get renamed along with the photos.

    Returns:
        {missing photo_file: new photo_file}
    """
    pairs: dict[str, str] = {}
    groups: dict[str, tuple[list[str], list[str]]] = {}
    for f in missing:
        groups.setdefault(_name_parts(f)[0], ([], []))[0].append(f)
    for f in new:
        key = _name_parts(f)[0]
        if key in groups:
            groups[key][1].append(f)

    for olds, news in groups.values():
        if len(olds) == 1 and len(news) == 1:
            pairs[olds[0]] = news[0]
            continue
        for slot in {_name_parts(f)[1] for f in olds}:
            old_slot = [f for f in olds if _name_parts(f)[1] == slot]
            new_slot = [f for f in news if _name_parts(f)[1] == slot]
            if len(old_slot) == 1 and len(new_slot) == 1:
                pairs[old_slot[0]] = new_slot[0]

    # A date edited in the name: pair across dates on a unique stamp id
    by_id: dict[str, tuple[list[str], list[str]]] = {}
    for i, files in enumerate((missing, new)):
        for f in files:
            if f in pairs or f in pairs.values():
                continue
            m = FILE_NAME_RE.match(Path(f).stem)
            if m and m.group("stamp").isdigit():
                by_id.setdefault(m.group("stamp"), ([], []))[i].append(f)
    for olds, news in by_id.values():
        if len(olds) == 1 and len(news) == 1:
            pairs[olds[0]] = news[0]
    return pairs


def repoint_missing(df_log: pd.DataFrame) -> dict[str, str]:
    """Re-point rows whose photo was moved or renamed by hand.

    A missing photo is matched to an unlogged photo with the same file name,
    ignoring the location slot, so moving a photo between trips or editing
    its location in the name keeps the row and its hand-entered details.
    Photos still unmatched are paired within their trip and date (see
    _pair_leftovers), which covers a stamp id edited in the name; the new id
    is then taken in by adopt_name_edits.

    Returns:
        {old photo_file: new photo_file} for each re-pointed photo.
    """
    logged = set(df_log["photo_file"])
    by_key: dict[str, list[str]] = {}
    for p in PHOTO_DIR.rglob("*"):
        if p.suffix.lower() in PHOTO_SUFFIXES:
            rel = p.relative_to(PHOTO_DIR).as_posix()
            if rel not in logged:
                by_key.setdefault(_match_key(p.name), []).append(rel)

    targets: dict[str, str] = {}
    missing = sorted({f for f in logged if not (PHOTO_DIR / f).exists()})
    for old in missing:
        matches = by_key.get(_match_key(Path(old).name), [])
        if len(matches) == 1:
            targets[old] = matches[0]

    leftover_old = [f for f in missing if f not in targets]
    leftover_new = sorted(
        f for fs in by_key.values() for f in fs if f not in targets.values()
    )
    targets |= _pair_leftovers(leftover_old, leftover_new)

    for old, new in targets.items():
        df_log.loc[df_log["photo_file"] == old, "photo_file"] = new
        logger.info("Re-pointed %s → %s", old, new)
    return targets


def warn_missing(df_log: pd.DataFrame) -> None:
    """Warn about rows whose photo is still missing after re-pointing."""
    for f in sorted({f for f in df_log["photo_file"] if not (PHOTO_DIR / f).exists()}):
        logger.warning("%s → photo missing (deleted? then delete its row)", f)


def name_location(location_id: str, mail_type: str) -> str:
    """The location slot a photo name gets from its log row.

    Mailed stamps are named by their mail_type (ml1 / ml2 / ml3, or "mail"
    while undecided) even when the mailing station is known; the station
    stays in the log's location_id.
    """
    if mail_type:
        return mail_type
    return location_id.lower() if location_id else UNKNOWN_LOCATION


def _adopt_name_stamp_id(df_log: pd.DataFrame, idx: int, name_id: str) -> bool:
    """Take a stamp id typed into a single-stamp photo's name into the log.

    Returns:
        True if the row changed.
    """
    photo_file = df_log.at[idx, "photo_file"]
    if (df_log["photo_file"] == photo_file).sum() > 1:
        return False  # several stamps in one photo: the name can't say which
    old_id = df_log.at[idx, "stamp_id"]
    if name_id == old_id:
        return False
    # Text belongs to the old id; the map refills it (retired: type it by hand)
    df_log.loc[idx, ["stamp_id", "stamp_text"]] = [name_id, ""]
    logger.info(
        "%s → stamp id %s taken from the name (was %s)",
        photo_file,
        name_id,
        old_id or "blank",
    )
    return True


def _adopt_name_date(df_log: pd.DataFrame, idx: int) -> bool:
    """Take a date typed into a single-stamp photo's name into the log.

    Returns:
        True if the row changed.
    """
    photo_file = df_log.at[idx, "photo_file"]
    if (df_log["photo_file"] == photo_file).sum() > 1:
        return False  # a page can hold stamps from several days
    m = NAME_DATE_RE.match(Path(photo_file).stem)
    name_date = _parse_compact_date(m.group(1)) if m else None
    old_date = df_log.at[idx, "date_collected"]
    if name_date is None or name_date.isoformat() == old_date:
        return False
    df_log.loc[idx, ["date_collected", "date_source"]] = [
        name_date.isoformat(),
        "filename",
    ]
    logger.info(
        "%s → date %s taken from the name (was %s)",
        photo_file,
        name_date,
        old_date or "blank",
    )
    return True


def adopt_name_edits(df_log: pd.DataFrame, photo_files: set[str]) -> int:
    """Take dates, stamp ids and locations typed into photo names into the log.

    Only photos renamed by hand (re-pointed) or new to the log are read: for
    those the name is the latest edit, so it wins over the log, including hand
    entries. Anywhere else a disagreement comes from editing the log, which
    wins, and the next sync renames the photo to match.

    Args:
        df_log: The stamp log, updated in place.
        photo_files: Photos whose names are the latest edit.

    Name slots:
        <location_id>  Collected at that station (location_source = file_name).
                       On a mailed row this records the mailing station, and
                       the next sync renames the photo back to its mail type.
        ml1/ml2/ml3    Received by mail: sets mail_type to that NPTC code.
                       Also clears guessed same-day locations (see
                       _fill_locations).
        mail           Received by mail, code undecided: sets mail_type to
                       "mail" unless the row already has a code.
        unknown        Carries no information; ignored.

    Returns:
        Number of rows changed.
    """
    n = 0
    for idx in df_log.index[df_log["photo_file"].isin(photo_files)]:
        m = FILE_NAME_RE.match(Path(df_log.at[idx, "photo_file"]).stem)
        if m and (m.group("stamp").isdigit() or m.group("stamp").lower() == PERSONAL):
            n += _adopt_name_stamp_id(df_log, idx, m.group("stamp").lower())
        n += _adopt_name_date(df_log, idx)
        slot = (m.group("location") or "").lower() if m else ""
        row = df_log.loc[idx]
        if slot in ("", UNKNOWN_LOCATION):
            continue
        if slot in MAIL_TYPES:
            keep_code = slot == MAIL_LOCATION and row["mail_type"] in MAIL_CODES
            if slot != row["mail_type"] and not keep_code:
                df_log.at[idx, "mail_type"] = slot
                logger.info(
                    "%s → mail_type %s taken from the name", row["photo_file"], slot
                )
                n += 1
            continue
        if slot == row["location_id"].lower():
            continue
        df_log.loc[idx, ["location_id", "location_name", "location_source"]] = [
            slot.upper(),
            "",
            "file_name",
        ]
        logger.info("%s → location %s taken from the name", row["photo_file"], slot)
        n += 1
    return n


def main() -> None:
    """Add new stamp photos to the log and fill in details for entered IDs."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    register_heif_opener()

    # -------------------------------------------------------------------------------- #
    # 🗺️ LOAD MASTER MAP
    # -------------------------------------------------------------------------------- #
    export = latest_export()
    locations = load_stamping_locations(export)
    logger.info(
        "Loaded %s stamping locations from %s", f"{len(locations):,}", export.name
    )

    # -------------------------------------------------------------------------------- #
    # 📥 SCAN PHOTOS
    # -------------------------------------------------------------------------------- #
    df_log = load_log()

    # Photos moved or renamed by hand keep their rows (and hand-entered details)
    # instead of coming back as new photos
    renamed = set(repoint_missing(df_log).values())

    # Adopting a crop frees its raw page photo, so scan again afterwards
    for photo in _find_new_photos(df_log, PHOTO_DIR):
        if _adopt_crop(df_log, photo):
            renamed.add(photo.relative_to(PHOTO_DIR).as_posix())
    new_photos = _find_new_photos(df_log, PHOTO_DIR)
    warn_missing(df_log)
    new_rows = [build_row(p, PHOTO_DIR) for p in new_photos]
    for row in new_rows:
        if row["date_source"] in ("trip_start", "photo_unverified", ""):
            logger.warning(
                "%s → approximate date (%s: %s)",
                row["photo_file"],
                row["date_source"] or "none",
                row["date_collected"] or "missing",
            )

    # -------------------------------------------------------------------------------- #
    # ✍️ UPDATE LOG
    # -------------------------------------------------------------------------------- #
    df_log = pd.concat(
        [df_log, pd.DataFrame(new_rows, columns=LOG_COLUMNS)], ignore_index=True
    )
    new_files = {row["photo_file"] for row in new_rows}
    adopt_name_edits(df_log, renamed | new_files)
    n_filled = _fill_from_map(df_log, locations)
    df_log = df_log.sort_values(["date_collected", "photo_file", "stamp_id"])
    df_log[LOG_COLUMNS].to_csv(LOG_CSV, index=False)

    n_missing_id = int((df_log["stamp_id"] == "").sum())
    logger.info(
        "Stamp log updated\n"
        "  ├── New photos:        %s\n"
        "  ├── Stamp text filled: %s\n"
        "  └── Rows missing id:   %s",
        f"{len(new_rows):,}",
        f"{n_filled:,}",
        f"{n_missing_id:,}",
    )
    if n_missing_id:
        logger.info(
            "Fill stamp_id in %s (one row per stamp; duplicate a row when a photo "
            "shows several stamps), then re-run.",
            LOG_CSV.relative_to(PROJECT_ROOT),
        )


if __name__ == "__main__":
    main()
