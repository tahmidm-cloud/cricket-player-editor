#!/usr/bin/env python3
"""
Batting average vs pace/spin by format using:
- player.json = ONLY the batters/players you want output for
- cricinfo_player_metadata_clean(3).csv = fallback bowler info source for bowling type/hand
- Cricsheet people.csv = maps Cricinfo IDs to Cricsheet UUIDs
- Cricsheet Test/ODI/T20 JSON ZIPs = ball-by-ball data

This fixes the missing-bowler problem:
Your output stays limited to players in player.json, but the bowler's pace/spin type can come
from the metadata CSV even if that bowler is not in player.json.

Run in Codespaces:
python3 see.py --players player.json --metadata-csv "cricinfo_player_metadata_clean(3).csv" --out out_batting_vs_spin_pace --only-print-with-data

Main output:
out_batting_vs_spin_pace/batting_vs_spin_pace_ALL_PLAYERS_wide.csv

Definitions:
- Batting average vs pace/spin = batter runs vs that type / batter outs vs that type
- Strike rate vs pace/spin = batter runs * 100 / balls faced vs that type
- Runs = batter runs only
- Balls faced excludes wides and no-balls
- Outs counted when batter is player_out on that delivery, excluding retired hurt/out/not out
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
import urllib.request
from collections import defaultdict, Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CRICSHEET_URLS = {
    "test": "https://cricsheet.org/downloads/tests_json.zip",
    "odi": "https://cricsheet.org/downloads/odis_json.zip",
    "t20": "https://cricsheet.org/downloads/t20s_json.zip",
}

PEOPLE_CSV_URL = "https://cricsheet.org/register/people.csv"

VALID_BOWLING_TYPES = {"pace", "spin"}

NOT_OUT_DISMISSAL_KINDS = {
    "retired hurt",
    "retired out",
    "retired not out",
}


@dataclass
class PlayerInfo:
    player_id: str
    name: str
    full_name: str
    nationality: str
    role: str
    batting_hand: str | None
    bowling_hand: str | None
    bowling_type: str | None
    bowling_style: str | None
    cricsheet_id: str | None = None
    source: str = "player_json"


@dataclass
class BowlerInfo:
    cricinfo_id: str
    name: str
    country: str
    bowling_hand: str | None
    bowling_type: str | None
    bowling_style: str | None
    cricsheet_id: str | None = None
    source: str = "metadata_csv"


def clean_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in {"none", "null", "na", "n/a", "-"}:
        return None
    return s


def download_file(url: str, path: Path, force: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and path.stat().st_size > 0 and not force:
        print(f"Using cached: {path}", flush=True)
        return

    print(f"Downloading: {url}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 cricket-data-script"})
    with urllib.request.urlopen(req, timeout=180) as response:
        data = response.read()

    path.write_bytes(data)
    print(f"Saved: {path} ({path.stat().st_size:,} bytes)", flush=True)


def load_players(players_path: Path) -> list[dict[str, Any]]:
    with players_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and isinstance(data.get("players"), list):
        return data["players"]

    if isinstance(data, list):
        return data

    raise ValueError("player.json must be either a list or an object with a 'players' list.")


def get_player_id(player: dict[str, Any]) -> str | None:
    for key in ["id", "playerId", "player_id", "cricinfo_id", "final_cricinfo_id"]:
        value = clean_str(player.get(key))
        if value:
            return str(value)
    return None


def normalize_bowling_type(value: Any) -> str | None:
    s = clean_str(value)
    if not s:
        return None

    s = s.lower().strip()

    if s in {"pace", "fast", "seam", "medium", "fast-medium", "medium-fast"}:
        return "pace"

    if s in {"spin", "spinner", "slow"}:
        return "spin"

    return None


def infer_bowling_type_from_style(style: Any) -> str | None:
    s = (clean_str(style) or "").lower()

    if any(x in s for x in [
        "off break", "offbreak", "leg break", "legbreak", "googly",
        "orthodox", "wrist spin", "spin", "slow left", "slow left-arm"
    ]):
        return "spin"

    if any(x in s for x in ["fast", "medium", "seam", "swing", "pace"]):
        return "pace"

    return None


def normalize_bowling_hand(value: Any, style: Any = None) -> str | None:
    s = (clean_str(value) or "").lower()

    if s in {"right", "right hand", "right-arm", "right arm"}:
        return "right"

    if s in {"left", "left hand", "left-arm", "left arm"}:
        return "left"

    style_text = (clean_str(style) or "").lower()
    if "left-arm" in style_text or "left arm" in style_text or "slow left" in style_text:
        return "left"
    if "right-arm" in style_text or "right arm" in style_text or "off break" in style_text or "leg break" in style_text or "legbreak" in style_text:
        return "right"

    return None


def normalize_batting_hand(value: Any) -> str | None:
    s = (clean_str(value) or "").lower()
    if s in {"right", "right hand", "right-hand bat", "right hand bat", "rhb"}:
        return "right"
    if s in {"left", "left hand", "left-hand bat", "left hand bat", "lhb"}:
        return "left"
    return clean_str(value)


def load_people_register(people_csv_path: Path) -> dict[str, str]:
    """
    Return mapping:
    ESPNcricinfo ID -> Cricsheet identifier
    """
    text = people_csv_path.read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    mapping: dict[str, str] = {}

    for row in reader:
        cricsheet_identifier = clean_str(row.get("identifier"))
        cricinfo_id = clean_str(row.get("key_cricinfo"))

        if cricsheet_identifier and cricinfo_id:
            mapping[str(cricinfo_id)] = cricsheet_identifier

    return mapping


def load_metadata_bowlers(metadata_csv_path: Path) -> dict[str, BowlerInfo]:
    """
    Return:
    cricinfo_id -> BowlerInfo

    This file is used as a bowler info source, not as the output player list.
    """
    by_cricinfo_id: dict[str, BowlerInfo] = {}

    if not metadata_csv_path.exists():
        raise FileNotFoundError(f"Metadata CSV not found: {metadata_csv_path}")

    with metadata_csv_path.open("r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            cricinfo_id = clean_str(row.get("cricinfo_id"))
            if not cricinfo_id:
                continue

            bowling_style = clean_str(row.get("bowling_style")) or clean_str(row.get("meta_bowling_style"))
            bowling_type = normalize_bowling_type(row.get("bowling_type")) or infer_bowling_type_from_style(bowling_style)
            bowling_hand = normalize_bowling_hand(row.get("bowling_hand"), bowling_style)

            # Keep all metadata rows, but only rows with bowling type become usable for classification.
            by_cricinfo_id[str(cricinfo_id)] = BowlerInfo(
                cricinfo_id=str(cricinfo_id),
                name=clean_str(row.get("name")) or clean_str(row.get("meta_known_as")) or clean_str(row.get("full_name")) or str(cricinfo_id),
                country=clean_str(row.get("country")) or clean_str(row.get("meta_country")) or "",
                bowling_hand=bowling_hand,
                bowling_type=bowling_type,
                bowling_style=bowling_style,
                source="metadata_csv",
            )

    return by_cricinfo_id


def build_player_index(players: list[dict[str, Any]]) -> dict[str, PlayerInfo]:
    by_cricinfo_id: dict[str, PlayerInfo] = {}

    for p in players:
        player_id = get_player_id(p)
        if not player_id:
            continue

        bowling_style = clean_str(p.get("bowlingStyle"))
        bowling_type = normalize_bowling_type(p.get("bowlingType")) or infer_bowling_type_from_style(bowling_style)
        bowling_hand = normalize_bowling_hand(p.get("bowlingHand"), bowling_style)

        info = PlayerInfo(
            player_id=player_id,
            name=clean_str(p.get("name")) or clean_str(p.get("fullName")) or player_id,
            full_name=clean_str(p.get("fullName")) or clean_str(p.get("name")) or player_id,
            nationality=clean_str(p.get("nationality")) or "",
            role=clean_str(p.get("role")) or "",
            batting_hand=normalize_batting_hand(p.get("battingHand")),
            bowling_hand=bowling_hand,
            bowling_type=bowling_type,
            bowling_style=bowling_style,
            source="player_json",
        )
        by_cricinfo_id[player_id] = info

    return by_cricinfo_id


def attach_player_cricsheet_ids(
    players_by_cricinfo_id: dict[str, PlayerInfo],
    cricinfo_to_cricsheet: dict[str, str],
) -> dict[str, PlayerInfo]:
    """
    Return:
    Cricsheet identifier -> PlayerInfo

    This is ONLY for batters/output players from player.json.
    """
    by_cricsheet_id: dict[str, PlayerInfo] = {}

    for cricinfo_id, player in players_by_cricinfo_id.items():
        cs_id = cricinfo_to_cricsheet.get(str(cricinfo_id))
        if not cs_id:
            continue

        player.cricsheet_id = cs_id
        by_cricsheet_id[cs_id] = player

    return by_cricsheet_id


def build_bowler_source_by_cricsheet_id(
    players_by_cricinfo_id: dict[str, PlayerInfo],
    metadata_bowlers_by_cricinfo_id: dict[str, BowlerInfo],
    cricinfo_to_cricsheet: dict[str, str],
) -> dict[str, BowlerInfo]:
    """
    Bowler source priority:
    1. metadata CSV, because user requested it as the fallback source
    2. player.json info, for player rows not in metadata or where metadata lacks type

    This source can include bowlers outside player.json.
    Output players/batters still stay limited to player.json.
    """
    by_cricsheet_id: dict[str, BowlerInfo] = {}

    # First add metadata bowlers
    for cricinfo_id, b in metadata_bowlers_by_cricinfo_id.items():
        cs_id = cricinfo_to_cricsheet.get(str(cricinfo_id))
        if not cs_id:
            continue
        b.cricsheet_id = cs_id
        by_cricsheet_id[cs_id] = b

    # Then fill gaps from player.json, or improve if metadata has no bowling type
    for cricinfo_id, p in players_by_cricinfo_id.items():
        cs_id = cricinfo_to_cricsheet.get(str(cricinfo_id))
        if not cs_id:
            continue

        candidate = BowlerInfo(
            cricinfo_id=cricinfo_id,
            name=p.name,
            country=p.nationality,
            bowling_hand=p.bowling_hand,
            bowling_type=p.bowling_type,
            bowling_style=p.bowling_style,
            cricsheet_id=cs_id,
            source="player_json",
        )

        existing = by_cricsheet_id.get(cs_id)
        if existing is None:
            by_cricsheet_id[cs_id] = candidate
        elif existing.bowling_type not in VALID_BOWLING_TYPES and candidate.bowling_type in VALID_BOWLING_TYPES:
            by_cricsheet_id[cs_id] = candidate

    return by_cricsheet_id


def registry_id(match: dict[str, Any], player_name: str) -> str | None:
    registry = (((match.get("info") or {}).get("registry") or {}).get("people") or {})
    return registry.get(player_name)


def counts_as_ball_faced(delivery: dict[str, Any]) -> bool:
    extras = delivery.get("extras") or {}
    return "wides" not in extras and "noballs" not in extras


def batter_runs_from_delivery(delivery: dict[str, Any]) -> int:
    runs = delivery.get("runs") or {}
    return int(runs.get("batter", 0) or 0)


def batter_out_on_delivery(delivery: dict[str, Any], batter_name: str) -> tuple[int, list[str]]:
    wickets = delivery.get("wickets") or []
    out_count = 0
    kinds: list[str] = []

    for wicket in wickets:
        player_out = wicket.get("player_out")
        kind = str(wicket.get("kind") or "").lower().strip()

        if player_out == batter_name and kind not in NOT_OUT_DISMISSAL_KINDS:
            out_count += 1
            kinds.append(kind)

    return out_count, kinds


def new_bucket() -> dict[str, Any]:
    return {
        "runs": 0,
        "balls": 0,
        "outs": 0,
        "fours": 0,
        "sixes": 0,
        "dotBalls": 0,
        "deliveriesSeen": 0,
        "dismissalKinds": Counter(),
        "metadataBowlerDeliveries": 0,
        "playerJsonBowlerDeliveries": 0,
    }


def add_delivery_to_bucket(
    bucket: dict[str, Any],
    delivery: dict[str, Any],
    outs: int,
    dismissal_kinds: list[str],
    bowler_source: str,
) -> None:
    runs = batter_runs_from_delivery(delivery)
    balls = 1 if counts_as_ball_faced(delivery) else 0

    bucket["runs"] += runs
    bucket["balls"] += balls
    bucket["outs"] += outs
    bucket["deliveriesSeen"] += 1

    if bowler_source == "metadata_csv":
        bucket["metadataBowlerDeliveries"] += 1
    elif bowler_source == "player_json":
        bucket["playerJsonBowlerDeliveries"] += 1

    if balls == 1 and runs == 0:
        bucket["dotBalls"] += 1

    if runs == 4:
        bucket["fours"] += 1
    if runs == 6:
        bucket["sixes"] += 1

    for kind in dismissal_kinds:
        bucket["dismissalKinds"][kind] += 1


def safe_average(runs: int, outs: int) -> float | None:
    if outs <= 0:
        return None
    return round(runs / outs, 2)


def safe_strike_rate(runs: int, balls: int) -> float | None:
    if balls <= 0:
        return None
    return round(runs * 100 / balls, 2)


def safe_percent(num: int, den: int) -> float | None:
    if den <= 0:
        return None
    return round(num * 100 / den, 2)


def dismissal_kind_text(counter: Counter) -> str:
    if not counter:
        return ""
    return "; ".join(f"{kind}:{count}" for kind, count in sorted(counter.items()))


def bucket_public_stats(bucket: dict[str, Any]) -> dict[str, Any]:
    runs = int(bucket["runs"])
    balls = int(bucket["balls"])
    outs = int(bucket["outs"])
    fours = int(bucket["fours"])
    sixes = int(bucket["sixes"])
    dot_balls = int(bucket["dotBalls"])
    boundary_runs = fours * 4 + sixes * 6

    return {
        "runs": runs,
        "balls": balls,
        "outs": outs,
        "average": safe_average(runs, outs),
        "strikeRate": safe_strike_rate(runs, balls),
        "fours": fours,
        "sixes": sixes,
        "boundaryRuns": boundary_runs,
        "boundaryRunPercent": safe_percent(boundary_runs, runs),
        "dotBalls": dot_balls,
        "dotBallPercent": safe_percent(dot_balls, balls),
        "deliveriesSeen": int(bucket["deliveriesSeen"]),
        "metadataBowlerDeliveries": int(bucket["metadataBowlerDeliveries"]),
        "playerJsonBowlerDeliveries": int(bucket["playerJsonBowlerDeliveries"]),
        "dismissalKinds": dismissal_kind_text(bucket["dismissalKinds"]),
    }


def process_match_json(
    match: dict[str, Any],
    fmt: str,
    batters_by_cricsheet_id: dict[str, PlayerInfo],
    bowler_source_by_cricsheet_id: dict[str, BowlerInfo],
    player_type_breakdown: dict[tuple[str, str, str], dict[str, Any]],
    unmatched: Counter,
) -> None:
    innings = match.get("innings") or []

    for innings_obj in innings:
        overs = innings_obj.get("overs") or []

        for over in overs:
            deliveries = over.get("deliveries") or []

            for delivery in deliveries:
                batter_name = delivery.get("batter")
                bowler_name = delivery.get("bowler")

                if not batter_name or not bowler_name:
                    continue

                batter_cs_id = registry_id(match, batter_name)
                bowler_cs_id = registry_id(match, bowler_name)

                if not batter_cs_id:
                    unmatched[("batter_no_registry", batter_name)] += 1
                    continue
                if not bowler_cs_id:
                    unmatched[("bowler_no_registry", bowler_name)] += 1
                    continue

                # Batter/output is ONLY players from player.json.
                batter = batters_by_cricsheet_id.get(batter_cs_id)
                if not batter:
                    unmatched[("batter_not_in_player_json_output_list", batter_name)] += 1
                    continue

                # Bowler classification can come from metadata CSV or player.json.
                bowler = bowler_source_by_cricsheet_id.get(bowler_cs_id)
                if not bowler:
                    unmatched[("bowler_not_in_metadata_or_player_json", bowler_name)] += 1
                    continue

                bowling_type = bowler.bowling_type
                if bowling_type not in VALID_BOWLING_TYPES:
                    unmatched[("bowler_missing_pace_spin_type", bowler_name)] += 1
                    continue

                outs, dismissal_kinds = batter_out_on_delivery(delivery, batter_name)

                key = (fmt, batter.player_id, bowling_type)
                add_delivery_to_bucket(
                    player_type_breakdown[key],
                    delivery,
                    outs,
                    dismissal_kinds,
                    bowler.source,
                )


def process_zip(
    zip_path: Path,
    fmt: str,
    batters_by_cricsheet_id: dict[str, PlayerInfo],
    bowler_source_by_cricsheet_id: dict[str, BowlerInfo],
    player_type_breakdown: dict[tuple[str, str, str], dict[str, Any]],
    unmatched: Counter,
    print_match_progress_every: int,
) -> int:
    matches_processed = 0

    with zipfile.ZipFile(zip_path, "r") as zf:
        json_names = [n for n in zf.namelist() if n.endswith(".json")]

        for index, name in enumerate(json_names, start=1):
            try:
                with zf.open(name) as f:
                    match = json.load(f)

                process_match_json(
                    match=match,
                    fmt=fmt,
                    batters_by_cricsheet_id=batters_by_cricsheet_id,
                    bowler_source_by_cricsheet_id=bowler_source_by_cricsheet_id,
                    player_type_breakdown=player_type_breakdown,
                    unmatched=unmatched,
                )

                matches_processed += 1
            except Exception as exc:
                print(f"WARNING: Could not process {name}: {exc}", file=sys.stderr, flush=True)

            if print_match_progress_every and index % print_match_progress_every == 0:
                print(f"{fmt.upper()}: processed {index:,}/{len(json_names):,} matches...", flush=True)

    print(f"{fmt.upper()}: finished {matches_processed:,} matches.", flush=True)
    return matches_processed


def make_wide_rows(
    formats: list[str],
    all_players: dict[str, PlayerInfo],
    player_type_breakdown: dict[tuple[str, str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []

    for fmt in formats:
        for player_id, player in sorted(all_players.items(), key=lambda item: (item[1].nationality, item[1].name)):
            pace_bucket = player_type_breakdown.get((fmt, player_id, "pace"), new_bucket())
            spin_bucket = player_type_breakdown.get((fmt, player_id, "spin"), new_bucket())

            pace = bucket_public_stats(pace_bucket)
            spin = bucket_public_stats(spin_bucket)

            rows.append({
                "format": fmt,
                "playerId": player_id,
                "name": player.name,
                "fullName": player.full_name,
                "nationality": player.nationality,
                "role": player.role,
                "battingHand": player.batting_hand or "",
                "hasCricsheetId": "yes" if player.cricsheet_id else "no",

                "paceRuns": pace["runs"],
                "paceBalls": pace["balls"],
                "paceOuts": pace["outs"],
                "paceAverage": pace["average"],
                "paceStrikeRate": pace["strikeRate"],
                "paceFours": pace["fours"],
                "paceSixes": pace["sixes"],
                "paceMetadataBowlerDeliveries": pace["metadataBowlerDeliveries"],
                "pacePlayerJsonBowlerDeliveries": pace["playerJsonBowlerDeliveries"],

                "spinRuns": spin["runs"],
                "spinBalls": spin["balls"],
                "spinOuts": spin["outs"],
                "spinAverage": spin["average"],
                "spinStrikeRate": spin["strikeRate"],
                "spinFours": spin["fours"],
                "spinSixes": spin["sixes"],
                "spinMetadataBowlerDeliveries": spin["metadataBowlerDeliveries"],
                "spinPlayerJsonBowlerDeliveries": spin["playerJsonBowlerDeliveries"],
            })

    return rows


def make_long_rows(
    formats: list[str],
    all_players: dict[str, PlayerInfo],
    player_type_breakdown: dict[tuple[str, str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []

    for fmt in formats:
        for player_id, player in sorted(all_players.items(), key=lambda item: (item[1].nationality, item[1].name)):
            for bowling_type in ["pace", "spin"]:
                bucket = player_type_breakdown.get((fmt, player_id, bowling_type), new_bucket())
                stats = bucket_public_stats(bucket)

                rows.append({
                    "format": fmt,
                    "playerId": player_id,
                    "name": player.name,
                    "fullName": player.full_name,
                    "nationality": player.nationality,
                    "role": player.role,
                    "battingHand": player.batting_hand or "",
                    "hasCricsheetId": "yes" if player.cricsheet_id else "no",
                    "bowlingTypeFaced": bowling_type,
                    **stats,
                })

    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = list(rows[0].keys())

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_format_results(
    fmt: str,
    all_players: dict[str, PlayerInfo],
    player_type_breakdown: dict[tuple[str, str, str], dict[str, Any]],
    only_with_data: bool,
) -> None:
    print()
    print("=" * 118)
    print(f"{fmt.upper()} BATTERS — VS PACE / VS SPIN")
    print("=" * 118)
    print(
        f"{'Name':30} {'Nation':14} "
        f"{'Pace Avg':>9} {'Pace Runs':>10} {'Pace Balls':>10} "
        f"{'Spin Avg':>9} {'Spin Runs':>10} {'Spin Balls':>10} "
        f"{'MetaDelivs':>10}"
    )
    print("-" * 118)

    printed = 0

    for player_id, player in sorted(all_players.items(), key=lambda item: (item[1].nationality, item[1].name)):
        pace_bucket = player_type_breakdown.get((fmt, player_id, "pace"), new_bucket())
        spin_bucket = player_type_breakdown.get((fmt, player_id, "spin"), new_bucket())

        pace = bucket_public_stats(pace_bucket)
        spin = bucket_public_stats(spin_bucket)

        total_balls = pace["balls"] + spin["balls"]
        total_runs = pace["runs"] + spin["runs"]

        if only_with_data and total_balls == 0 and total_runs == 0:
            continue

        pace_avg = "-" if pace["average"] is None else str(pace["average"])
        spin_avg = "-" if spin["average"] is None else str(spin["average"])
        meta_delivs = pace["metadataBowlerDeliveries"] + spin["metadataBowlerDeliveries"]

        print(
            f"{player.name[:30]:30} {player.nationality[:14]:14} "
            f"{pace_avg:>9} {pace['runs']:>10} {pace['balls']:>10} "
            f"{spin_avg:>9} {spin['runs']:>10} {spin['balls']:>10} "
            f"{meta_delivs:>10}",
            flush=True
        )
        printed += 1

    print("-" * 118)
    print(f"Printed players: {printed}")
    print("=" * 118)
    print()


def write_mapping_report(
    path: Path,
    players_by_cricinfo_id: dict[str, PlayerInfo],
    metadata_bowlers_by_cricinfo_id: dict[str, BowlerInfo],
    cricinfo_to_cricsheet: dict[str, str],
) -> None:
    rows = []

    for player_id, player in sorted(players_by_cricinfo_id.items(), key=lambda item: (item[1].nationality, item[1].name)):
        cs_id = cricinfo_to_cricsheet.get(player_id)
        meta = metadata_bowlers_by_cricinfo_id.get(player_id)

        rows.append({
            "playerId": player_id,
            "name": player.name,
            "fullName": player.full_name,
            "nationality": player.nationality,
            "role": player.role,
            "battingHand": player.batting_hand or "",
            "playerJsonBowlingType": player.bowling_type or "",
            "playerJsonBowlingHand": player.bowling_hand or "",
            "playerJsonBowlingStyle": player.bowling_style or "",
            "metadataFoundForSameId": "yes" if meta else "no",
            "metadataName": meta.name if meta else "",
            "metadataCountry": meta.country if meta else "",
            "metadataBowlingType": meta.bowling_type if meta else "",
            "metadataBowlingHand": meta.bowling_hand if meta else "",
            "metadataBowlingStyle": meta.bowling_style if meta else "",
            "hasCricsheetRegisterMatch": "yes" if cs_id else "no",
            "cricsheetId": cs_id or "",
        })

    write_csv(path, rows)


def write_bowler_source_report(path: Path, bowler_source_by_cricsheet_id: dict[str, BowlerInfo]) -> None:
    rows = []

    for cs_id, b in sorted(bowler_source_by_cricsheet_id.items(), key=lambda item: (item[1].country, item[1].name)):
        rows.append({
            "cricsheetId": cs_id,
            "cricinfoId": b.cricinfo_id,
            "name": b.name,
            "country": b.country,
            "bowlingType": b.bowling_type or "",
            "bowlingHand": b.bowling_hand or "",
            "bowlingStyle": b.bowling_style or "",
            "source": b.source,
            "usablePaceSpin": "yes" if b.bowling_type in VALID_BOWLING_TYPES else "no",
        })

    write_csv(path, rows)


def write_unmatched_report(path: Path, unmatched: Counter) -> None:
    rows = []
    for (reason, name), count in sorted(unmatched.items(), key=lambda item: item[1], reverse=True):
        rows.append({
            "reason": reason,
            "name": name,
            "deliveryCount": count,
        })
    write_csv(path, rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--players", default="player.json", help="Path to your output player JSON file.")
    parser.add_argument("--metadata-csv", default="cricinfo_player_metadata_clean(3).csv", help="Metadata CSV used for bowler pace/spin lookup.")
    parser.add_argument("--out", default="out_batting_vs_spin_pace", help="Output folder.")
    parser.add_argument("--cache", default=".cricsheet_cache", help="Download cache folder.")
    parser.add_argument("--force-download", action="store_true", help="Redownload Cricsheet files even if cached.")
    parser.add_argument("--only-print-with-data", action="store_true", help="Print only players who have balls/runs in that format. CSV still includes everyone.")
    parser.add_argument("--print-match-progress-every", type=int, default=250, help="Print match progress every N matches. Use 0 to disable.")
    args = parser.parse_args()

    players_path = Path(args.players)
    metadata_csv_path = Path(args.metadata_csv)
    out_dir = Path(args.out)
    cache_dir = Path(args.cache)

    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    people_csv_path = cache_dir / "people.csv"
    download_file(PEOPLE_CSV_URL, people_csv_path, force=args.force_download)

    zip_paths = {}
    for fmt, url in CRICSHEET_URLS.items():
        zip_path = cache_dir / f"{fmt}s_json.zip"
        download_file(url, zip_path, force=args.force_download)
        zip_paths[fmt] = zip_path

    players = load_players(players_path)
    players_by_cricinfo_id = build_player_index(players)
    metadata_bowlers_by_cricinfo_id = load_metadata_bowlers(metadata_csv_path)
    cricinfo_to_cricsheet = load_people_register(people_csv_path)

    batters_by_cricsheet_id = attach_player_cricsheet_ids(players_by_cricinfo_id, cricinfo_to_cricsheet)
    bowler_source_by_cricsheet_id = build_bowler_source_by_cricsheet_id(
        players_by_cricinfo_id=players_by_cricinfo_id,
        metadata_bowlers_by_cricinfo_id=metadata_bowlers_by_cricinfo_id,
        cricinfo_to_cricsheet=cricinfo_to_cricsheet,
    )

    usable_bowler_sources = sum(
        1 for b in bowler_source_by_cricsheet_id.values()
        if b.bowling_type in VALID_BOWLING_TYPES
    )
    metadata_bowler_sources = sum(
        1 for b in bowler_source_by_cricsheet_id.values()
        if b.source == "metadata_csv" and b.bowling_type in VALID_BOWLING_TYPES
    )
    player_json_bowler_sources = sum(
        1 for b in bowler_source_by_cricsheet_id.values()
        if b.source == "player_json" and b.bowling_type in VALID_BOWLING_TYPES
    )

    print()
    print("INPUT SUMMARY")
    print("-" * 70)
    print(f"Players/output batters in player.json: {len(players_by_cricinfo_id):,}")
    print(f"Output batters matched to Cricsheet ID: {len(batters_by_cricsheet_id):,}")
    print(f"Metadata CSV rows loaded: {len(metadata_bowlers_by_cricinfo_id):,}")
    print(f"Usable bowler pace/spin sources: {usable_bowler_sources:,}")
    print(f"  from metadata CSV: {metadata_bowler_sources:,}")
    print(f"  from player.json fallback: {player_json_bowler_sources:,}")
    print("-" * 70)
    print()

    player_type_breakdown: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(new_bucket)
    unmatched: Counter = Counter()
    match_counts = {}

    formats = ["test", "odi", "t20"]

    for fmt in formats:
        print(f"STARTING {fmt.upper()}...", flush=True)
        match_counts[fmt] = process_zip(
            zip_path=zip_paths[fmt],
            fmt=fmt,
            batters_by_cricsheet_id=batters_by_cricsheet_id,
            bowler_source_by_cricsheet_id=bowler_source_by_cricsheet_id,
            player_type_breakdown=player_type_breakdown,
            unmatched=unmatched,
            print_match_progress_every=args.print_match_progress_every,
        )

        print_format_results(
            fmt=fmt,
            all_players=players_by_cricinfo_id,
            player_type_breakdown=player_type_breakdown,
            only_with_data=args.only_print_with_data,
        )

    wide_rows = make_wide_rows(formats, players_by_cricinfo_id, player_type_breakdown)
    long_rows = make_long_rows(formats, players_by_cricinfo_id, player_type_breakdown)

    wide_path = out_dir / "batting_vs_spin_pace_ALL_PLAYERS_wide.csv"
    long_path = out_dir / "batting_vs_spin_pace_ALL_PLAYERS_long.csv"
    mapping_path = out_dir / "player_json_mapping_report.csv"
    bowler_source_path = out_dir / "bowler_source_metadata_report.csv"
    unmatched_path = out_dir / "cricsheet_unmatched_report.csv"

    write_csv(wide_path, wide_rows)
    write_csv(long_path, long_rows)
    write_mapping_report(mapping_path, players_by_cricinfo_id, metadata_bowlers_by_cricinfo_id, cricinfo_to_cricsheet)
    write_bowler_source_report(bowler_source_path, bowler_source_by_cricsheet_id)
    write_unmatched_report(unmatched_path, unmatched)

    print()
    print("DONE")
    print("-" * 70)
    print(f"Matches processed: {match_counts}")
    print(f"Wide all-player CSV: {wide_path}")
    print(f"Long all-player CSV: {long_path}")
    print(f"Player mapping report: {mapping_path}")
    print(f"Bowler source metadata report: {bowler_source_path}")
    print(f"Unmatched report: {unmatched_path}")
    print("-" * 70)
    print()


if __name__ == "__main__":
    main()
