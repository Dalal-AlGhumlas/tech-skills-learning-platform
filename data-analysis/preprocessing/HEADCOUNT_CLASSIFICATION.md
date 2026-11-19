Headcount full-dataset classification
====================================

Run these PowerShell commands from the repository root:

```powershell
Set-Location C:\Users\Dalal\tech-skills-learning-platform

# Offline regression tests (mocked model, temporary outputs).
python -m unittest discover -s data-analysis/preprocessing -p test_classify_headcount.py -v

# Check cache reuse and export all jobs without any model calls.
python data-analysis/preprocessing/classify_headcount.py --classify-all --provider ollama --model qwen2.5:7b --max-chars 3000 --max-new 0

# Confirm the local model is installed; Ollama must be running.
ollama list

# Small live smoke test: classify at most 2 unfinished jobs.
python data-analysis/preprocessing/classify_headcount.py --classify-all --provider ollama --model qwen2.5:7b --max-chars 3000 --max-new 2

# Run a batch. Repeat this exact command to resume successive batches.
python data-analysis/preprocessing/classify_headcount.py --classify-all --provider ollama --model qwen2.5:7b --max-chars 3000 --max-new 100 --max-retries 2

# Inspect completion and failures after each batch.
Get-Content data-analysis/preprocessing/output/headcount/ai_classification/full_dataset/report_all.json
```

If `qwen2.5:7b` is missing, install it with `ollama pull qwen2.5:7b`.
Ctrl+C stops a batch; the same command resumes it. Keep provider, model and
`--max-chars` identical between runs to reuse the same cache. The existing V3
prompt, schema, validation, nine categories and temperature (0) are unchanged.

`--max-new` limits distinct unfinished jobs attempted in a batch, including
failed jobs. `--max-retries 2` permits at most three calls per attempted job,
with bounded backoff and the existing 240-second Ollama request timeout.
Failures are retried on the next invocation; successful jobs are skipped.

Outputs live exclusively in
`data-analysis/preprocessing/output/headcount/ai_classification/full_dataset/`:

- `classifications_all.csv` and `classifications_all.jsonl` contain every job,
  including out-of-scope jobs and pending/failed rows with blank/null decisions.
  Source fields and identifiers are retained; `original_job` also preserves the
  complete original object, including fields that might collide with metadata.
- `report_all.json` records processed, remaining, failed, cache reused, newly
  classified, attempted jobs, actual model calls and decision counts.
- `classification_cache.jsonl` saves each success immediately, flushed and
  synced to disk. Matching successful V3 sample-cache entries are copied here
  without modifying the sample cache. An interrupted final append is ignored
  on read and repaired before the next append.
- `failures.jsonl` records exhausted failures for later retry. Historical errors
  remain in this log after recovery; the report counts only unresolved failures.

CSV/JSONL/report exports are atomically replaced individually on startup and
exit, including Ctrl+C. During a running batch the progress journal is current;
after force termination rerun the command to rebuild exports from that journal.
Pending jobs are distinct from the model decision `needs_review`.

Use one classifier process at a time for this output directory. Completion is
`remaining: 0` and `incomplete: false`. Existing sample exports, human labels and
the normalized source dataset are never written by `--classify-all`.

The original `--prepare`, `--classify-sample`, and `--evaluate` modes retain
their existing behavior and output locations.
