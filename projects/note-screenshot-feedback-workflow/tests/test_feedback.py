import copy
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import feedback as f

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="note-feedback-test-")
        self.conn = f.connect(Path(self.temp.name) / "feedback.db")
        self.before = f.load_json(FIXTURES / "before.json")
        self.current = f.load_json(FIXTURES / "current.json")

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def both(self):
        f.ingest(self.conn, self.before)
        f.ingest(self.conn, self.current)

    def reviews(self):
        self.both()
        f.save_review(self.conn, f.load_json(FIXTURES / "review-before.json"))
        f.save_review(self.conn, f.load_json(FIXTURES / "review-current.json"))

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]

    def test_renamed_and_reordered_input_is_duplicate(self):
        f.ingest(self.conn, self.before)
        repeated = copy.deepcopy(self.before)
        repeated.update(id="another-name", source="renamed.png")
        repeated["articles"].reverse()
        self.assertEqual(f.ingest(self.conn, repeated), {"status": "duplicate", "id": "demo-before"})
        self.assertEqual(self.count(), 1)

    def test_conflicting_observation_rolls_back_and_keeps_original(self):
        f.ingest(self.conn, self.before)
        changed = copy.deepcopy(self.before)
        changed["id"] = "conflict"
        changed["totals"]["page_views"] += 1
        changed["articles"][0]["page_views"] += 1
        with self.assertRaisesRegex(ValueError, "conflicting"):
            f.ingest(self.conn, changed)
        self.assertFalse(self.conn.in_transaction)
        self.assertEqual(self.count(), 1)
        self.assertEqual(f.snapshot(self.conn, "demo-before"), self.before)
        self.assertEqual(f.ingest(self.conn, self.current)["status"], "inserted")

    def test_same_id_cannot_be_reused(self):
        f.ingest(self.conn, self.before)
        self.current["id"] = "demo-before"
        with self.assertRaisesRegex(ValueError, "id already"):
            f.ingest(self.conn, self.current)
        self.assertEqual(self.count(), 1)

    def test_negative_boolean_and_string_metrics_rejected(self):
        for bad in (-1, True, "100", 1.5):
            with self.subTest(bad=bad):
                value = copy.deepcopy(self.before)
                value["totals"]["page_views"] = bad
                with self.assertRaises(ValueError):
                    f.ingest(self.conn, value)
        self.assertEqual(self.count(), 0)

    def test_complete_total_mismatch_rejected_incomplete_retained(self):
        self.before["articles"].pop()
        with self.assertRaisesRegex(ValueError, "total mismatch"):
            f.ingest(self.conn, self.before)
        self.before["articles_complete"] = False
        f.ingest(self.conn, self.before)
        self.assertEqual(self.count(), 1)

    def test_unknown_metric_and_new_article_are_not_zero(self):
        self.before["totals"]["likes"] = None
        self.before["articles"].pop()
        self.before["articles_complete"] = False
        self.both()
        result = f.compare(self.conn, "demo-before", "demo-current")
        self.assertIsNone(result["totals"]["likes"])
        self.assertIsNone(result["articles"][1]["page_views"])
        self.assertTrue(any("incomplete" in warning for warning in result["warnings"]))

    def test_rolling_difference_and_unknown_timezone_warning(self):
        self.both()
        result = f.compare(self.conn, "demo-before", "demo-current")
        self.assertEqual(result["totals"], {"impressions": 200, "page_views": 12, "likes": 2})
        self.assertEqual(result["label"], "observed_difference")
        self.assertEqual(len(result["warnings"]), 2)

    def test_negative_difference_is_preserved(self):
        self.current["totals"]["page_views"] = 90
        self.current["articles"][0]["page_views"] = 48
        self.both()
        self.assertEqual(f.compare(self.conn, "demo-before", "demo-current")["totals"]["page_views"], -10)

    def test_different_accounts_and_timezones_cannot_be_compared(self):
        self.current["account"] = "second"
        self.both()
        with self.assertRaisesRegex(ValueError, "different accounts"):
            f.compare(self.conn, "demo-before", "demo-current")
        third = copy.deepcopy(self.before)
        third.update(id="timezone-known", updated_at="2026-11-13T10:00:00", timezone="+09:00")
        f.ingest(self.conn, third)
        with self.assertRaisesRegex(ValueError, "timezone"):
            f.compare(self.conn, "demo-before", "timezone-known")
        self.assertEqual(f.context(self.conn, "demo")["comparison"]["status"], "held")

    def test_reversed_time_is_rejected(self):
        self.both()
        with self.assertRaisesRegex(ValueError, "older"):
            f.compare(self.conn, "demo-current", "demo-before")

    def test_context_carries_unmentioned_hypothesis_and_latest_evaluation(self):
        self.reviews()
        result = f.context(self.conn, "demo")
        states = {item["id"]: item for item in result["hypotheses"]}
        self.assertEqual(states["h-howto"]["status"], "inconclusive")
        self.assertEqual(states["h-search"]["status"], "pending")
        self.assertEqual(states["h-search"]["last_review_id"], "review-before")
        self.assertEqual(result["latest_review"]["applied_changes"], [])

    def test_review_requires_known_snapshot_valid_status_and_evidence(self):
        self.both()
        original = f.load_json(FIXTURES / "review-before.json")
        invalid = copy.deepcopy(original)
        invalid["snapshot_id"] = "missing"
        with self.assertRaisesRegex(ValueError, "unknown snapshot"):
            f.save_review(self.conn, invalid)
        invalid = copy.deepcopy(original)
        invalid["hypotheses"][0]["status"] = "proved"
        with self.assertRaisesRegex(ValueError, "status"):
            f.save_review(self.conn, invalid)
        invalid["hypotheses"][0]["status"] = "supports"
        with self.assertRaisesRegex(ValueError, "evidence"):
            f.save_review(self.conn, invalid)

    def test_claim_change_needs_new_id(self):
        self.reviews()
        changed = f.load_json(FIXTURES / "review-current.json")
        changed["id"] = "changed-review"
        changed["hypotheses"][0]["claim"] = "別の仮説"
        with self.assertRaisesRegex(ValueError, "new id"):
            f.save_review(self.conn, changed)

    def test_context_uses_display_time_not_ingestion_order(self):
        f.ingest(self.conn, self.current)
        f.ingest(self.conn, self.before)
        result = f.context(self.conn, "demo")
        self.assertEqual(result["latest_observations"][-1]["id"], "demo-current")
        self.assertEqual(result["comparison"]["totals"]["page_views"], 12)

    def test_context_keeps_other_account_out(self):
        self.reviews()
        other = copy.deepcopy(self.current)
        other.update(id="other-account", account="other", updated_at="2026-11-14T12:00:00")
        f.ingest(self.conn, other)
        result = f.context(self.conn, "other")
        self.assertEqual(len(result["latest_observations"]), 1)
        self.assertEqual(result["hypotheses"], [])
        self.assertIsNone(result["latest_review"])

    def test_decision_requires_actual_text_and_known_candidate(self):
        self.reviews()
        for candidate, instruction, scope in (("missing", "作成", "記事"),
                                              ("candidate-howto", "", "記事"),
                                              ("candidate-howto", "作成", "")):
            with self.assertRaises(ValueError):
                f.decision(self.conn, "review-current", candidate, "approve", instruction, scope)
        f.decision(self.conn, "review-current", "candidate-howto", "defer", "教材用の保留例", "執筆なし")
        self.assertEqual(f.context(self.conn, "demo")["decisions"][0]["choice"], "defer")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 1)

    def test_duplicate_json_keys_rejected(self):
        target = Path(self.temp.name) / "duplicate.json"
        target.write_text('{"id":"a","id":"b"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            f.load_json(target)

    def test_cli_bad_input_returns_error_without_rows(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            code = f.main(["--db", str(Path(self.temp.name) / "cli.db"), "ingest", str(FIXTURES / "missing.json")])
        self.assertEqual(code, 2)
        self.assertIn('"error"', error.getvalue())


if __name__ == "__main__":
    unittest.main()
