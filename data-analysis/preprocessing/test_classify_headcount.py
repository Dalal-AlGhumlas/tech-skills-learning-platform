"""Offline regression tests; all writes use temporary output directories."""

import contextlib
import csv
import importlib.util
import io
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "classify_headcount", Path(__file__).with_name("classify_headcount.py")
)
c = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(c)


class FullClassificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "ai_classification"
        self.output.mkdir()
        for name, value in {
            "OUTPUT": self.output,
            "CACHE": self.output / "classification_cache.jsonl",
            "SAMPLE": self.output / "sample_100.csv",
        }.items():
            p = patch.object(c, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.args = Namespace(provider="ollama", model="qwen2.5:7b",
                              max_chars=3000, max_new=100, max_retries=2)
        self.jobs = {}
        for index in range(5):
            job = {"source": "headcount_labs", "source_job_id": str(index),
                   "url": f"https://example.test/{index}", "job_title": "Chef",
                   "description": "Prepare food.", "custom_field": {"id": index}}
            self.jobs[c.key_for(job)] = job
        self.stdout = contextlib.redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)

    def prediction(self, job, *_):
        return c.validate_result({
            "decision": "out_of_scope", "specialization": None,
            "confidence": "high", "reason": "Food preparation.",
            "evidence": job["job_title"],
        }, job), False

    def run_all(self, response=None):
        with patch.object(c, "request_model", side_effect=response or self.prediction) as model:
            c.classify_all(self.jobs, self.args)
        return model

    def rows(self):
        return c.read_journal(self.output / "full_dataset/classifications_all.jsonl")

    def report(self):
        return json.loads((self.output / "full_dataset/report_all.json").read_text())

    def seed_cache(self, key=None):
        key = key or next(iter(self.jobs))
        result, truncated = self.prediction(self.jobs[key])
        item = {"cache_key": c.cache_key(key, self.jobs[key], self.args.provider,
                                        self.args.model, self.args.max_chars),
                "result": result, "description_truncated": truncated}
        c.append_journal(c.CACHE, item)
        return item

    def test_batch_resume_and_cache_reuse_preserve_outputs(self):
        self.seed_cache()
        protected = [c.CACHE, c.SAMPLE,
                     self.output / "classifications_sample_100.csv",
                     self.output / "headcount_sample_100_human_review_3.csv"]
        for path in protected[1:]:
            path.write_bytes(b"human labels and original sample\r\n")
        before = {path: path.read_bytes() for path in protected}
        self.args.max_new = 2
        self.assertEqual(self.run_all().call_count, 2)
        self.assertEqual(self.report()["cache_reused"], 1)
        self.assertEqual(self.report()["processed"], 3)
        self.assertEqual(len(self.rows()), 5)
        self.assertEqual(self.run_all().call_count, 2)
        self.assertEqual(self.report()["processed"], 5)
        self.assertEqual(self.run_all().call_count, 0)
        self.assertFalse(self.report()["incomplete"])
        self.assertEqual(before, {path: path.read_bytes() for path in protected})
        for row in self.rows():
            self.assertEqual(row["original_job"], self.jobs[row["record_key"]])
            self.assertEqual(row["decision"], "out_of_scope")
            self.assertTrue(row["evidence_verified"])
            self.assertTrue(set(c.RESULT_FIELDS) <= row.keys())

    def test_keyboard_interrupt_commits_then_resumes(self):
        result = self.prediction(next(iter(self.jobs.values())))
        with self.assertRaises(KeyboardInterrupt):
            self.run_all([result, KeyboardInterrupt()])
        self.assertEqual(self.report()["processed"], 1)
        # Simulate an abruptly terminated write after the last committed record.
        journal = self.output / "full_dataset/classification_cache.jsonl"
        with journal.open("ab") as file:
            file.write(b'{"cache_key": "torn')
        self.assertEqual(self.run_all().call_count, 4)
        self.assertEqual(len(c.read_journal(journal)), 5)
        self.assertEqual(self.run_all().call_count, 0)

    def test_failures_are_bounded_recorded_and_retried(self):
        self.args.max_new = 2
        with patch.object(c.time, "sleep"):
            model = self.run_all(RuntimeError("Ollama unavailable"))
        self.assertEqual(model.call_count, 6)
        self.assertEqual(self.report()["failed"], 2)
        self.assertEqual(self.report()["remaining"], 5)
        self.assertEqual([row["classification_status"] for row in self.rows()],
                         ["failed", "failed", "pending", "pending", "pending"])
        self.run_all()
        self.assertEqual(self.report()["failed"], 0)
        self.assertEqual(self.report()["processed"], 2)
        self.assertEqual(len(c.read_journal(self.output / "full_dataset/failures.jsonl")), 2)

    def test_cache_invalidated_by_settings_version_and_job_text(self):
        key = next(iter(self.jobs))
        original = self.seed_cache(key)
        base = original["cache_key"]
        for field, value in [("model", "other"), ("provider", "openai"),
                             ("max_chars", 15000)]:
            settings = vars(self.args) | {field: value}
            self.assertNotEqual(base, c.cache_key(key, self.jobs[key],
                                settings["provider"], settings["model"], settings["max_chars"]))
        for field in ("job_title", "description", "source_job_id"):
            job = self.jobs[key] | {field: "changed"}
            self.assertNotEqual(base, c.cache_key(c.key_for(job), job, "ollama", "qwen2.5:7b", 3000))
        with patch.object(c, "VERSION", "headcount-classifier-v2"):
            self.assertNotEqual(base, c.cache_key(key, self.jobs[key], "ollama", "qwen2.5:7b", 3000))
        # An incomplete old cache entry must not suppress classification.
        del original["result"]["evidence_verified"]
        c.CACHE.write_text(json.dumps(original) + "\n", encoding="utf-8")
        self.assertEqual(self.run_all().call_count, 5)

    def test_real_dataset_completeness_and_source_preservation(self):
        source_digest = c.hashlib.sha256(c.INPUT.read_bytes()).digest()
        self.jobs = c.load_jobs()
        self.assertEqual(len(self.jobs), 8807)
        self.args.max_new = len(self.jobs)
        # Journal durability is exercised by the focused tests. This exhaustive
        # test checks model coverage and real exports without 8,807 file opens.
        with patch.object(c, "append_journal") as journal:
            self.assertEqual(self.run_all().call_count, 8807)
        self.assertEqual(journal.call_count, 8807)
        rows = self.rows()
        self.assertEqual(len(rows), 8807)
        self.assertEqual({row["record_key"] for row in rows}, set(self.jobs))
        for row in rows:
            self.assertEqual(row["original_job"], self.jobs[row["record_key"]])
            self.assertEqual(row["classification_status"], "completed")
        csv.field_size_limit(10_000_000)
        with (self.output / "full_dataset/classifications_all.csv").open(
                encoding="utf-8-sig", newline="") as file:
            csv_rows = list(csv.DictReader(file))
        self.assertEqual(len(csv_rows), 8807)
        self.assertEqual({row["record_key"] for row in csv_rows}, set(self.jobs))
        self.assertEqual(self.report()["decisions"]["out_of_scope"], 8807)
        self.assertEqual(c.hashlib.sha256(c.INPUT.read_bytes()).digest(), source_digest)

    def test_zero_budget_exports_every_job_without_model_calls(self):
        self.args.max_new = 0
        self.assertEqual(self.run_all().call_count, 0)
        self.assertEqual(len(self.rows()), len(self.jobs))
        self.assertEqual(self.report()["remaining"], len(self.jobs))

    def test_sample_and_evaluate_still_work(self):
        key = next(iter(self.jobs))
        with c.SAMPLE.open("w", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=["record_key", "human_decision",
                                                     "human_specialization"])
            writer.writeheader()
            writer.writerow({"record_key": key, "human_decision": "out_of_scope",
                             "human_specialization": ""})
        with patch.object(c, "request_model", side_effect=self.prediction):
            c.classify(self.jobs, [key], self.args, "sample_100")
        c.evaluate()
        self.assertEqual(json.loads((self.output / "evaluation_report.json").read_text())
                         ["decision_accuracy"], 1.0)
        with self.assertRaisesRegex(SystemExit, "Sample already exists"):
            c.make_sample(self.jobs)


if __name__ == "__main__":
    unittest.main()
