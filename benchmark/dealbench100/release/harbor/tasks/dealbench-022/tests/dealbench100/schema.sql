PRAGMA foreign_keys = ON;

CREATE TABLE projects (
  project_code TEXT PRIMARY KEY,
  company TEXT NOT NULL,
  industry TEXT NOT NULL,
  deal_type TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE files (
  file_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  logical_name TEXT NOT NULL,
  name TEXT NOT NULL,
  version INTEGER NOT NULL,
  is_current INTEGER NOT NULL,
  kind TEXT NOT NULL,
  content_json TEXT NOT NULL
);
CREATE TABLE messages (
  message_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  subject TEXT NOT NULL,
  sender TEXT NOT NULL,
  recipients_json TEXT NOT NULL,
  body TEXT NOT NULL,
  sent_at TEXT NOT NULL,
  task_id TEXT
);
CREATE TABLE chat_messages (
  message_id TEXT PRIMARY KEY,
  channel TEXT NOT NULL,
  thread_id TEXT,
  author TEXT NOT NULL,
  text TEXT NOT NULL,
  posted_at TEXT NOT NULL,
  task_id TEXT
);
CREATE TABLE workbooks (
  workbook_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  name TEXT NOT NULL,
  revision TEXT NOT NULL,
  ranges_json TEXT NOT NULL
);
CREATE TABLE companies (
  company_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE comparables (
  comparable_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  company TEXT NOT NULL,
  ev_ebitda REAL NOT NULL,
  approved INTEGER NOT NULL
);
CREATE TABLE transactions (
  transaction_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  target TEXT NOT NULL,
  ev_ebitda REAL NOT NULL,
  approved INTEGER NOT NULL
);
CREATE TABLE models (
  model_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  revision TEXT NOT NULL,
  status TEXT NOT NULL,
  outputs_json TEXT NOT NULL,
  source_refs_json TEXT NOT NULL,
  last_task_id TEXT
);
CREATE TABLE bids (
  bid_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  bidder TEXT NOT NULL,
  headline_value REAL NOT NULL,
  certainty REAL NOT NULL,
  condition_penalty REAL NOT NULL,
  status TEXT NOT NULL,
  rationale TEXT,
  last_task_id TEXT
);
CREATE TABLE diligence_findings (
  finding_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  severity TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL,
  resolution TEXT,
  last_task_id TEXT
);
CREATE TABLE approvals (
  approval_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  status TEXT NOT NULL,
  authority TEXT NOT NULL,
  evidence_refs_json TEXT NOT NULL,
  last_task_id TEXT
);
CREATE TABLE deliverables (
  deliverable_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  revision TEXT NOT NULL,
  status TEXT NOT NULL,
  values_json TEXT NOT NULL,
  unrelated_slides_sha256 TEXT NOT NULL,
  last_task_id TEXT
);
CREATE TABLE plans (
  plan_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  task_id TEXT NOT NULL UNIQUE,
  decision TEXT NOT NULL,
  status TEXT NOT NULL,
  rationale TEXT NOT NULL,
  source_refs_json TEXT NOT NULL,
  model_id TEXT NOT NULL,
  deliverable_id TEXT NOT NULL
);
CREATE TABLE sent_messages (
  sent_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  task_id TEXT NOT NULL,
  recipient TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  review_status TEXT NOT NULL
);
CREATE TABLE chat_posts (
  post_id TEXT PRIMARY KEY,
  channel TEXT NOT NULL,
  task_id TEXT NOT NULL,
  text TEXT NOT NULL,
  review_status TEXT NOT NULL
);
CREATE TABLE workbook_changes (
  change_id TEXT PRIMARY KEY,
  workbook_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  cell_range TEXT NOT NULL,
  values_json TEXT NOT NULL
);
CREATE TABLE submissions (
  task_id TEXT PRIMARY KEY,
  answers_json TEXT NOT NULL
);
CREATE TABLE audit_log (
  audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
  task_id TEXT,
  tool TEXT NOT NULL,
  target TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
