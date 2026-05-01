CREATE TABLE IF NOT EXISTS extraction_patterns (
  pattern_id          TEXT PRIMARY KEY,
  pattern_type        TEXT NOT NULL,
  format_fingerprint  TEXT NOT NULL,
  regex               TEXT NOT NULL,
  description         TEXT,
  example_match       TEXT,
  example_output      JSON,
  created_by          TEXT NOT NULL,
  status              TEXT NOT NULL DEFAULT 'pending_review',
  approved_by         TEXT,
  approved_at         TIMESTAMP,
  created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  match_count         INTEGER DEFAULT 0,
  success_count       INTEGER DEFAULT 0,
  last_matched_at     TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_patterns_fingerprint
  ON extraction_patterns(format_fingerprint, status);

CREATE INDEX IF NOT EXISTS idx_patterns_status
  ON extraction_patterns(status);

CREATE TABLE IF NOT EXISTS extraction_runs (
  run_id              TEXT PRIMARY KEY,
  document_name       TEXT NOT NULL,
  fingerprint         TEXT NOT NULL,
  patterns_used       JSON,
  llm_calls           INTEGER DEFAULT 0,
  rows_extracted      INTEGER DEFAULT 0,
  rows_low_confidence INTEGER DEFAULT 0,
  profile             TEXT,
  ran_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
