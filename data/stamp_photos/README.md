# Stamp Photos

Photos of collected cancellation stamps, kept as a personal record before (and
after) uploading to the NPTC site. **Images here are gitignored** — phone photos
embed GPS in their EXIF data, and the repo is pushed to GitHub. Back this folder
up outside git (e.g. iCloud).

## Naming convention

**Trip folders:** `YYYYMMDD_trip-name` for one day, `YYYYMMDD-YYYYMMDD_trip-name`
for several. Lowercase words joined by hyphens. Every photo lives in a trip
folder, even a single-stop outing — no loose files, no nested folders. One
trip, one folder: a stop within a longer trip goes in that trip's folder. The
folder's dates span the days stamps were collected, not the whole trip.

The trip name is the short name you'd say, not the park unit:

- No NPS designations (`congaree`, not `congaree-national-park`). The unit is
  in each photo's location and stamp text, and designations change.
- `state-park` for state parks only (`caesars-head-state-park`), to tell the
  two systems apart.
- A region or city for multi-stop trips (`new-england`, `yadkin-valley`).
- No abbreviations (`great-smoky-mountains`, not `gsmnp`).
- A personal tag at the end is fine (`-mollys-30th-birthday`).

**Stamp photos:** `YYYYMMDD__<location>__<stamp_id>.jpg` — the date the stamp
was **collected**, the lowercased `location_id` where it was collected, and its
NPTC stamp Id. One stamp per photo, cropped. For a stamp received by mail,
the location slot is its NPTC mail code instead (`ml1`, `ml2`, `ml3`, or
`mail` while undecided; see Logging). The mailing station, if known, stays in
the log. The slot is `unknown` when the location isn't known.

```
data/stamp_photos/
  20251206_cheraw-state-park/
    20251206__sc84__15824.jpg
  20260918-20260919_new-york-city/
    20260918__ny101__09219.jpg
    20260918__ny101__11045.jpg
    20260919__ny61__09199.jpg
```

| Case | Name |
|---|---|
| Same stamp collected twice on one day | `20260918__ny101__09219_2.jpg` |
| Retired or unidentified stamp | `20180608__ma10__unknown_bunker-hill.jpg` |
| Personal stamp (on NPTC, no stamp id) | `20230902__unknown__personal_fairy-stone-state-park.jpg` |
| Full-page shot worth keeping | `20180930_page_1.jpg` (logged as `stamp_id = none`) |
| Stamp from an earlier trip, photographed later | file under the trip it was collected on |

The script reads the date and stamp Id straight from the file name. Older
names (`20240614_24 - Pacific Northwest`, `2026-04-21/` subfolders, camera
names) still work, with the date guessed as described below.

Keep only the cropped copy here. If the original is kept too, name the crop
`X_cropped` next to `X`, or use `raw/` + `cropped/` folders; originals with a
cropped copy are skipped.

**Renaming:** don't rename photos by hand — the log is the source of truth.
Fix `stamp_id`, `date_collected` or the location in the log, then run:

```bash
uv run python -m scripts.sync_photo_names           # dry run: shows the plan
uv run python -m scripts.sync_photo_names --apply   # renames photos + log
```

The exceptions are the date, stamp id and location slot: editing any of them
in a name by hand (a station id, or a mail code) is taken into the log on the
next run of either script. The name wins over the log only for photos renamed
since the last run, so the log still wins after you edit it. Dates and ids
are only read from single-stamp photos, not `page` shots. The sync also moves a photo into the trip whose
dates contain its collection date.
Moving a photo or renaming a trip folder by hand is fine: rows are re-pointed
by file name on the next sync. `original_file` keeps each photo's first name.

**Cropping:** stamps only seen in a raw page photo are flagged `needs_crop`.
Crop one out, save it in the same trip folder as `YYYYMMDD_<stamp_id>.jpg`, and
run the logging script — the existing row moves to the crop.

## Logging

```bash
uv run python -m scripts.log_stamp_photos
```

This adds one row per new photo to
`data/manual_tracking/cancellation_stamp_log.csv` with a best-guess
`date_collected`. `date_source` says where it came from:

| date_source | Meaning |
|---|---|
| `stamp` | Date read off the cancellation itself (set by hand during review) |
| `filename` | Date at the start of the file name — most reliable automatic source |
| `subfolder` | Dated folder inside the trip folder, e.g. `2026-04-21/` |
| `photo` | Photo's EXIF date, within the trip folder's range |
| `trip_start` | Trip folder's start date — approximate |
| `photo_unverified` | EXIF date with no trip folder to check it against |

Photo GPS is ignored: stamps are usually photographed at the hotel or at home.

Then:

1. Fill in `stamp_id` for each row (the NPTC stamp Id). Use `none` for photos
   that aren't a single stamp to log (full-page shots, duplicates), with the
   reason in `notes`. Retired stamps aren't in the master map export, so their
   IDs have to come from parkstamps.org. Use `personal` for a stamp logged on
   NPTC as a personal stamp, which has no stamp id (e.g. Virginia state
   parks): type its `stamp_text` and `location_name` by hand.
2. If a photo shows several stamps, duplicate its row — one row per stamp.
3. Set `uploaded_to_nptc` to `Yes` once it's logged on the site.
4. `location_id` is the station where the stamp was **collected** (the same
   stamp is often kept at several stations). `location_source` says how it
   was set:

   | location_source | Meaning |
   |---|---|
   | `manual` | Entered or confirmed by hand (a blank id here means "not in the map") |
   | `file_name` | From a hint in the original file / folder name |
   | `only_station` | The master map lists the stamp at one station today |
   | `same_day` | Guessed: the one listed station visited that day — review these |

   Only rows with a blank `location_source` are filled automatically, so
   set it to `manual` when correcting one. The map is a current snapshot;
   stamps move between desks, so older `only_station` / `same_day` values
   are best guesses.
5. Set `stamped_elsewhere` to `Yes` for a stamp applied somewhere other than
   the station it was made for (e.g. a Sugarlands VC stamp used at another
   visitor center), and put the station where it was applied in
   `location_id`. The script warns when this disagrees with the map. Whether
   such stamps count is a filter, not an edit.
6. Set `mail_type` for a stamp received by mail, using the NPTC codes:

   | mail_type | Meaning |
   |---|---|
   | `ml1` | Mail, same year as the visit |
   | `ml2` | Mail, not the same year as the visit |
   | `ml3` | Mail, other (not tied to a visit, e.g. the NPTC membership stamp) |
   | `mail` | Mailed, code not decided yet |

   Blank means collected in person. Typing the code into the photo name's
   location slot works too (`mail` never overwrites a code already set).
   Everything collected before 2018-04-14 (Congaree, the first stamp
   collected in person) came by mail. `date_collected` is the date on the
   cancellation, or the visit date if unreadable. `location_id` is still
   filled when the map lists the stamp at one station (`only_station`), but
   never guessed from same-day stamps. If the stamp is kept at several
   stations and you don't know which one mailed it, leave `location_id`
   blank and set `location_source` to `manual`.
7. `retired` is set by the script on every run (don't edit it): `Yes` when
   the stamp id isn't in the current master map, which lists only active
   stamps. Retired stamps get their id from parkstamps.org and their
   `stamp_text` typed by hand.
8. Re-run the script: it fills `stamp_text` and open locations from the
   latest NPTC master map export in `data/raw/nptc/`.
