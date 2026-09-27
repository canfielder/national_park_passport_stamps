"""Rename stamp photos to match the stamp log (the log is the source of truth).

Applies the naming convention in data/stamp_photos/README.md:

    YYYYMMDD[-YYYYMMDD]_trip-name/            trip folders
      YYYYMMDD__<location>__<stamp_id>.jpg    one identified stamp
      YYYYMMDD__<location>__unknown_<desc>.jpg  unidentified / retired stamp
      YYYYMMDD__<location>__personal_<desc>.jpg personal stamp (no NPTC id)
      YYYYMMDD_page_<n>.jpg                   full-page, raw, or duplicate shots

<location> is the lowercased location_id where the stamp was collected, the
NPTC mail code (ml1 / ml2 / ml3, or "mail" while undecided) for a stamp
received by mail, or "unknown".

Photos are also moved into the trip whose dates contain their collection date
(e.g. a 2019 stamp re-photographed on a 2024 trip goes back to the 2019 trip).
Log rows whose photo went missing are re-pointed when a file with the same
name exists elsewhere, so moving a photo between folders by hand is safe. A
stamp id or location typed into a name by hand is taken into the log first.

Fix a wrong name by editing the log (stamp_id / date_collected) and re-running.

Usage:
    uv run python -m scripts.sync_photo_names           # dry run
    uv run python -m scripts.sync_photo_names --apply
"""

import logging
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from scripts.log_stamp_photos import (
    CROPPED_RE,
    LOG_COLUMNS,
    LOG_CSV,
    NAME_DATE_RE,
    PERSONAL,
    PHOTO_DIR,
    PHOTO_SUFFIXES,
    TRIP_DATE_RE,
    adopt_name_edits,
    load_log,
    name_location,
    parse_trip_range,
    repoint_missing,
    warn_missing,
)

logger = logging.getLogger(__name__)

# Dates trusted enough to move a photo to a different trip
RELOCATE_SOURCES = {"stamp", "filename", "subfolder", "photo"}

# Camera / screenshot names carry no description worth keeping
CAMERA_NAME_RE = re.compile(
    r"^((img|dsc|pxl|screenshot|photo|window)([\s_-].*)?|[\d\s_-]*)$", re.I
)

# Screenshot-style leading timestamp: "2019-12-25 16_12_04-..."
TIMESTAMP_RE = re.compile(r"^\d{4}-?\d{2}-?\d{2}[ _]\d{2}[_:]?\d{2}[_:]?\d{2}[\s_-]*")

SLUG_MAX = 40

# Trip folder already named by the convention: "20260918-20260919_new-york-city"
CONVENTION_TRIP_RE = re.compile(r"\d{8}(?:-\d{8})?_[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True)
class Trip:
    """A trip folder in the naming convention, with its date range."""

    folder: str
    start: date
    end: date


def _slug(text: str) -> str:
    """Lowercase, hyphen-joined words: 'Hot Springs & NP' → 'hot-springs-and-np'."""
    text = text.replace("&", " and ").replace("'", "").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    # Trim long slugs at a word boundary
    if len(slug) > SLUG_MAX:
        slug = slug[: SLUG_MAX + 1].rsplit("-", 1)[0]
    return slug


def _trip_name(start: date, end: date, label: str) -> str:
    """Build a convention trip folder name."""
    dates = f"{start:%Y%m%d}" + (f"-{end:%Y%m%d}" if end != start else "")
    slug = _slug(label)
    return f"{dates}_{slug}" if slug else dates


def _describe(stem: str) -> str:
    """Strip dates, 'misc_' and '_cropped' from a file stem, leaving the words."""
    stem = CROPPED_RE.sub("", stem)
    m = NAME_DATE_RE.match(stem)
    rest = stem[m.end() :] if m else re.sub(r"^misc_", "", stem, flags=re.I)
    rest = TIMESTAMP_RE.sub("", rest)
    return "" if CAMERA_NAME_RE.match(rest) else rest


def _trip_for(photo_file: str, collected: date | None) -> Trip | None:
    """Work out the convention trip folder a photo currently belongs to.

    Photos in a dated trip folder keep that trip; loose photos at the top level
    get a one-day trip named from their date and description.
    """
    parts = Path(photo_file).parts
    if len(parts) > 1:
        trip_range = parse_trip_range(parts[0])
        if trip_range is None:
            return None
        # A folder already in the convention keeps its name, even past SLUG_MAX
        if CONVENTION_TRIP_RE.fullmatch(parts[0]):
            return Trip(parts[0], *trip_range)
        label = TRIP_DATE_RE.sub("", parts[0])
        return Trip(_trip_name(*trip_range, label), *trip_range)
    if collected is None:
        return None
    label = _describe(Path(photo_file).stem)
    return Trip(_trip_name(collected, collected, label), collected, collected)


def _target_stem(df_photo: pd.DataFrame, collected: date) -> str:
    """Pick the base file name for a photo from its log rows (before numbering)."""
    ids = df_photo["stamp_id"].tolist()
    is_page = (
        len(df_photo) > 1 or "none" in ids or (df_photo["needs_crop"] == "Yes").any()
    )
    day = f"{collected:%Y%m%d}"
    if is_page:
        return f"{day}_page"
    row = df_photo.iloc[0]
    location = name_location(row["location_id"], row["mail_type"])
    prefix = f"{day}__{location}__"
    if ids[0].isdigit():
        return f"{prefix}{ids[0]}"
    if ids[0] == PERSONAL:
        # Keep the description already in the name, else build one
        m = re.search(r"__personal_(.+?)(?:_\d+)?$", Path(row["photo_file"]).stem)
        desc = m.group(1) if m else _slug(_describe(Path(row["original_file"]).stem))
        return f"{prefix}personal_{desc}" if desc else f"{prefix}personal"
    desc = _slug(_describe(Path(row["original_file"]).stem))
    return f"{prefix}unknown_{desc}" if desc else f"{prefix}unknown"


def plan_renames(df_log: pd.DataFrame) -> dict[str, str]:
    """Map each photo's current path to its convention path.

    Returns:
        {current photo_file: target photo_file}, only for photos that move.
    """
    df_log["_date"] = pd.to_datetime(df_log["date_collected"], errors="coerce").dt.date

    # Trip for every photo, then the set of trips to relocate into
    photos = []
    for photo_file, df_photo in df_log.groupby("photo_file", sort=True):
        # A stamp applied away from its station doesn't date the photo
        df_home = df_photo[df_photo["stamped_elsewhere"] != "Yes"]
        dates = (df_home if len(df_home) else df_photo)["_date"].dropna()
        collected = min(dates) if len(dates) else None
        trip = _trip_for(photo_file, collected)
        if trip is None or collected is None:
            logger.warning("%s → no trip folder or date; left as is", photo_file)
            continue
        photos.append((photo_file, df_photo, collected, trip))
    trips = {trip.folder: trip for *_, trip in photos}

    # Never hand out the name of a file that's on disk but not in the log
    logged = set(df_log["photo_file"])
    targets: dict[str, str] = {}
    taken = {
        p.relative_to(PHOTO_DIR).as_posix().lower()
        for p in PHOTO_DIR.rglob("*")
        if p.suffix.lower() in PHOTO_SUFFIXES
        and p.relative_to(PHOTO_DIR).as_posix() not in logged
    }
    for photo_file, df_photo, collected, trip in photos:
        # A photo dated outside its own trip goes to the one trip containing it
        trusted = df_photo["date_source"].isin(RELOCATE_SOURCES).all()
        if trusted and not trip.start <= collected <= trip.end:
            homes = [t for t in trips.values() if t.start <= collected <= t.end]
            if len(homes) == 1:
                trip = homes[0]

        stem = _target_stem(df_photo, collected)
        suffix = Path(photo_file).suffix.lower()

        # Number pages from 1; number repeats of any other name from 2
        n = 1
        while True:
            if stem.endswith("_page"):
                name = f"{stem}_{n}{suffix}"
            else:
                name = f"{stem}{'' if n == 1 else f'_{n}'}{suffix}"
            target = f"{trip.folder}/{name}"
            if target.lower() not in taken:
                break
            n += 1
        taken.add(target.lower())
        if target != photo_file:
            targets[photo_file] = target

    df_log.drop(columns="_date", inplace=True)
    return targets


def apply_renames(targets: dict[str, str]) -> None:
    """Move files in two phases so chains and swaps of names can't collide."""
    moving = set(targets)
    for target in targets.values():
        dest = PHOTO_DIR / target
        if dest.exists() and target not in moving:
            raise FileExistsError(f"Refusing to overwrite untracked file: {dest}")

    staged = {}
    for src in targets:
        tmp = (PHOTO_DIR / src).with_name(f".sync-{uuid.uuid4().hex}")
        (PHOTO_DIR / src).rename(tmp)
        staged[src] = tmp
    for src, tmp in staged.items():
        dest = PHOTO_DIR / targets[src]
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp.rename(dest)

    # Remove folders emptied by the moves (ignoring Finder's .DS_Store)
    for folder in sorted(PHOTO_DIR.rglob("*"), key=lambda p: -len(p.parts)):
        if folder.is_dir() and all(f.name == ".DS_Store" for f in folder.iterdir()):
            for f in folder.iterdir():
                f.unlink()
            folder.rmdir()


def main() -> None:
    """Plan (and with --apply, perform) renames to the naming convention."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    apply = "--apply" in sys.argv[1:]

    # -------------------------------------------------------------------------------- #
    # 📋 PLAN
    # -------------------------------------------------------------------------------- #
    df_log = load_log()
    repointed = repoint_missing(df_log)
    warn_missing(df_log)
    n_repointed = len(repointed)
    n_adopted = adopt_name_edits(df_log, set(repointed.values()))
    targets = plan_renames(df_log)
    for src, dest in sorted(targets.items()):
        logger.info("  %s\n    → %s", src, dest)

    n_folders = len({Path(d).parts[0] for d in targets.values()})
    logger.info(
        "Rename plan\n"
        "  ├── Photos to rename:  %s\n"
        "  ├── Target folders:    %s\n"
        "  ├── Rows re-pointed:   %s\n"
        "  └── Name edits taken:  %s",
        f"{len(targets):,}",
        f"{n_folders:,}",
        f"{n_repointed:,}",
        f"{n_adopted:,}",
    )
    if not apply:
        logger.info("Dry run — re-run with --apply to rename.")
        return

    # -------------------------------------------------------------------------------- #
    # 🚚 APPLY
    # -------------------------------------------------------------------------------- #
    apply_renames(targets)
    df_log["photo_file"] = df_log["photo_file"].replace(targets)
    df_log[LOG_COLUMNS].to_csv(LOG_CSV, index=False)
    logger.info("Renamed %s photos and updated %s", f"{len(targets):,}", LOG_CSV.name)


if __name__ == "__main__":
    main()
