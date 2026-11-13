"""Offline note feedback example. Standard library only; no network or LLM calls."""
import argparse
import hashlib
import json
import re
import sqlite3
import sys
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

METRICS = ("impressions", "page_views", "likes")
STATUSES = {"pending", "supports", "contradicts", "inconclusive"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
  seq INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE,
  identity_hash TEXT NOT NULL UNIQUE, payload TEXT NOT NULL, recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reviews (
  seq INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE,
  snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
  payload TEXT NOT NULL, recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
  seq INTEGER PRIMARY KEY, review_id TEXT NOT NULL REFERENCES reviews(id),
  candidate_id TEXT NOT NULL, choice TEXT NOT NULL,
  instruction TEXT NOT NULL, scope TEXT NOT NULL, recorded_at TEXT NOT NULL
);
"""


def require(condition, message):
    if not condition:
        raise ValueError(message)


def keys(value, expected, label):
    require(isinstance(value, dict) and set(value) == set(expected),
            f"{label}: expected keys {sorted(expected)}")


def nonempty(value, label):
    require(isinstance(value, str) and bool(value.strip()), f"{label}: nonempty text required")


def identifier(value, label):
    require(isinstance(value, str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value),
            f"{label}: use 1-64 lowercase letters, digits, _ or -")


def strings(value, label):
    require(isinstance(value, list), f"{label}: list required")
    for item in value:
        nonempty(item, label)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def now():
    return datetime.now(timezone.utc).isoformat()


def metrics(value, label):
    keys(value, METRICS, label)
    for key, number in value.items():
        require(number is None or (type(number) is int and number >= 0),
                f"{label}.{key}: nonnegative integer or null required")


def validate_snapshot(value):
    keys(value, ("schema_version", "id", "account", "period_start", "period_end",
                 "updated_at", "timezone", "source", "articles_complete", "totals", "articles"),
         "snapshot")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1,
            "unsupported schema_version")
    identifier(value["id"], "id")
    identifier(value["account"], "account")
    nonempty(value["source"], "source")
    for key in ("period_start", "period_end"):
        require(isinstance(value[key], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value[key]),
                f"{key}: YYYY-MM-DD required")
        date.fromisoformat(value[key])
    require(value["period_start"] <= value["period_end"], "period is reversed")
    stamp = value["updated_at"]
    require(isinstance(stamp, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", stamp),
            "updated_at: display time YYYY-MM-DDTHH:MM:SS required")
    datetime.fromisoformat(stamp)
    tz = value["timezone"]
    require(tz is None or (isinstance(tz, str) and re.fullmatch(r"[+-](?:0\d|1[0-4]):[0-5]\d", tz)),
            "timezone: null or fixed UTC offset such as +09:00 required")
    require(tz is None or not (tz[1:3] == "14" and tz[4:] != "00"), "invalid UTC offset")
    require(type(value["articles_complete"]) is bool, "articles_complete: boolean required")
    metrics(value["totals"], "totals")
    require(isinstance(value["articles"], list), "articles: list required")
    seen = set()
    for item in value["articles"]:
        keys(item, ("id", *METRICS), "article")
        identifier(item["id"], "article.id")
        require(item["id"] not in seen, "duplicate article id")
        seen.add(item["id"])
        metrics({key: item[key] for key in METRICS}, item["id"])
    for key in METRICS:
        values = [item[key] for item in value["articles"]]
        if value["articles_complete"] and value["totals"][key] is not None and all(v is not None for v in values):
            require(sum(values) == value["totals"][key], f"article total mismatch: {key}")
    result = json.loads(canonical(value))
    result["articles"].sort(key=lambda item: item["id"])
    return result


def semantic(value):
    # A renamed screenshot or input id is not a new observation.
    return {key: item for key, item in value.items() if key not in ("id", "source")}


def identity(value):
    fields = ("schema_version", "account", "period_start", "period_end", "updated_at", "timezone")
    return hashlib.sha256(canonical({key: value[key] for key in fields}).encode("utf-8")).hexdigest()


def connect(path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def snapshot(conn, snapshot_id):
    row = conn.execute("SELECT payload FROM snapshots WHERE id = ?", (snapshot_id,)).fetchone()
    require(row is not None, f"unknown snapshot: {snapshot_id}")
    return json.loads(row["payload"])


def ingest(conn, raw):
    value = validate_snapshot(raw)
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        by_id = conn.execute("SELECT payload FROM snapshots WHERE id = ?", (value["id"],)).fetchone()
        if by_id:
            require(semantic(json.loads(by_id["payload"])) == semantic(value), "id already used for different values")
        existing = conn.execute("SELECT id, payload FROM snapshots WHERE identity_hash = ?", (identity(value),)).fetchone()
        if existing:
            require(semantic(json.loads(existing["payload"])) == semantic(value),
                    "same observation has conflicting values; inspect the source, do not overwrite")
            return {"status": "duplicate", "id": existing["id"]}
        conn.execute("INSERT INTO snapshots (id, identity_hash, payload, recorded_at) VALUES (?, ?, ?, ?)",
                     (value["id"], identity(value), canonical(value), now()))
    return {"status": "inserted", "id": value["id"]}


def compare(conn, before_id, after_id):
    before, after = snapshot(conn, before_id), snapshot(conn, after_id)
    require(before["account"] == after["account"], "different accounts")
    require(before["timezone"] == after["timezone"], "different timezone labels; confirm before comparing")
    require(before["updated_at"] < after["updated_at"], "comparison requires an older and a newer display time")
    warnings = []
    if before["timezone"] is None:
        warnings.append("timezone_unknown: order follows display times; elapsed time is not calculated")
    old_period = (before["period_start"], before["period_end"])
    new_period = (after["period_start"], after["period_end"])
    if old_period != new_period:
        warnings.append("period_changed: observed difference, not daily growth")
    if not before["articles_complete"] or not after["articles_complete"]:
        warnings.append("article_list_incomplete: missing rows are not zero")

    def difference(old, new):
        return {key: None if old.get(key) is None or new.get(key) is None else new[key] - old[key]
                for key in METRICS}

    old_rows = {row["id"]: row for row in before["articles"]}
    new_rows = {row["id"]: row for row in after["articles"]}
    return {"before": before_id, "after": after_id, "label": "observed_difference",
            "warnings": warnings, "totals": difference(before["totals"], after["totals"]),
            "articles": [{"id": key, **difference(old_rows.get(key, {}), new_rows.get(key, {}))}
                         for key in sorted(old_rows.keys() | new_rows.keys())]}


def get_review(conn, review_id):
    row = conn.execute("SELECT payload FROM reviews WHERE id = ?", (review_id,)).fetchone()
    require(row is not None, f"unknown review: {review_id}")
    return json.loads(row["payload"])


def save_review(conn, value):
    keys(value, ("id", "snapshot_id", "previous_review_id", "facts", "hypotheses", "candidates", "applied_changes"), "review")
    identifier(value["id"], "review.id")
    current = snapshot(conn, value["snapshot_id"])
    for key in ("facts", "applied_changes"):
        strings(value[key], key)
    require(isinstance(value["hypotheses"], list), "hypotheses: list required")
    require(isinstance(value["candidates"], list), "candidates: list required")
    for collection in ("hypotheses", "candidates"):
        seen = set()
        for item in value[collection]:
            expected = ("id", "claim", "status", "evidence", "next_check") if collection == "hypotheses" else ("id", "title", "reader", "outcome", "needed")
            keys(item, expected, collection)
            identifier(item["id"], collection + ".id")
            require(item["id"] not in seen, f"duplicate {collection} id")
            seen.add(item["id"])
            for key in (("claim", "next_check") if collection == "hypotheses" else ("title", "reader", "outcome")):
                nonempty(item[key], key)
            strings(item["evidence"] if collection == "hypotheses" else item["needed"], collection)
            if collection == "hypotheses":
                require(item["status"] in STATUSES, "unknown hypothesis status")
                require(item["status"] == "pending" or bool(item["evidence"]), "evaluation requires evidence")
    previous = value["previous_review_id"]
    known_claims = {}
    for row in conn.execute("SELECT snapshot_id, payload FROM reviews"):
        if snapshot(conn, row["snapshot_id"])["account"] == current["account"]:
            for item in json.loads(row["payload"])["hypotheses"]:
                known_claims[item["id"]] = item["claim"]
    for item in value["hypotheses"]:
        if item["id"] in known_claims:
            require(item["claim"] == known_claims[item["id"]], "changed hypothesis claim needs a new id")
    if previous is not None:
        old = get_review(conn, previous)
        old_snapshot = snapshot(conn, old["snapshot_id"])
        require(old_snapshot["account"] == current["account"], "review belongs to different account")
        require(old_snapshot["updated_at"] < current["updated_at"], "previous review must refer to an older snapshot")
    with conn:
        existing = conn.execute("SELECT payload FROM reviews WHERE id = ?", (value["id"],)).fetchone()
        if existing:
            require(json.loads(existing["payload"]) == value, "review id already used; create a new review")
            return {"status": "duplicate", "id": value["id"]}
        conn.execute("INSERT INTO reviews (id, snapshot_id, payload, recorded_at) VALUES (?, ?, ?, ?)",
                     (value["id"], value["snapshot_id"], canonical(value), now()))
    return {"status": "inserted", "id": value["id"]}


def decision(conn, review_id, candidate_id, choice, instruction, scope):
    review = get_review(conn, review_id)
    require(candidate_id in {item["id"] for item in review["candidates"]}, "unknown candidate")
    require(choice in ("approve", "defer", "decline"), "unknown choice")
    nonempty(instruction, "instruction")
    nonempty(scope, "scope")
    with conn:
        cursor = conn.execute("""INSERT INTO decisions
            (review_id, candidate_id, choice, instruction, scope, recorded_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (review_id, candidate_id, choice, instruction, scope, now()))
    return {"status": "recorded", "seq": cursor.lastrowid,
            "note": "decision is a journal entry, not authentication or permission to publish"}


def context(conn, account):
    identifier(account, "account")
    observations = [json.loads(row["payload"]) for row in conn.execute("SELECT payload FROM snapshots ORDER BY seq")]
    observations = sorted((row for row in observations if row["account"] == account), key=lambda row: row["updated_at"])
    require(bool(observations), "no observations for this account")
    by_id = {row["id"]: row for row in observations}
    reviews = [json.loads(row["payload"]) for row in conn.execute("SELECT payload FROM reviews ORDER BY seq")]
    reviews = sorted((row for row in reviews if row["snapshot_id"] in by_id),
                     key=lambda row: by_id[row["snapshot_id"]]["updated_at"])
    hypotheses = {}
    for review in reviews:
        for item in review["hypotheses"]:
            hypotheses[item["id"]] = {**item, "last_review_id": review["id"]}
    review_ids = {row["id"] for row in reviews}
    decisions = [dict(row) for row in conn.execute("SELECT * FROM decisions ORDER BY seq") if row["review_id"] in review_ids]
    comparison = None
    if len(observations) >= 2:
        try:
            comparison = compare(conn, observations[-2]["id"], observations[-1]["id"])
        except ValueError as error:
            comparison = {"status": "held", "reason": str(error)}
    return {"account": account, "latest_observations": observations[-2:], "comparison": comparison,
            "hypotheses": list(hypotheses.values()), "latest_review": reviews[-1] if reviews else None,
            "decisions": decisions,
            "instruction": "Read the actual user instruction before drafting. No automatic publishing."}


def load_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), object_pairs_hook=unique_pairs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="local-only/feedback.db")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("ingest", "review"):
        sub.add_parser(name).add_argument("input")
    comparison = sub.add_parser("compare")
    comparison.add_argument("before")
    comparison.add_argument("after")
    selection = sub.add_parser("decision")
    selection.add_argument("review_id")
    selection.add_argument("candidate_id")
    selection.add_argument("--choice", required=True, choices=("approve", "defer", "decline"))
    selection.add_argument("--instruction", required=True)
    selection.add_argument("--scope", required=True)
    sub.add_parser("context").add_argument("account")
    args = parser.parse_args(argv)
    try:
        with closing(connect(args.db)) as conn:
            if args.command == "ingest":
                result = ingest(conn, load_json(args.input))
            elif args.command == "review":
                result = save_review(conn, load_json(args.input))
            elif args.command == "compare":
                result = compare(conn, args.before, args.after)
            elif args.command == "decision":
                result = decision(conn, args.review_id, args.candidate_id, args.choice, args.instruction, args.scope)
            else:
                result = context(conn, args.account)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, TypeError, KeyError, OSError, sqlite3.Error) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
