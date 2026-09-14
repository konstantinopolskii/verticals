-- verticals/db/migrations/003_idempotency.sql — WP-03. Shape from IR-04 and AC-001's explicit
-- criterion: primary key (owner, client_token) so `INSERT ... ON CONFLICT DO NOTHING` is how
-- two concurrent identical tokens fail to both write; `response_json` holds the replayed
-- response verbatim; the sweep index on (owner, created_at) is what lets every mutating write
-- delete its own owner's rows older than 24h in one indexed statement with no scheduler
-- (AC-199) — no cron, no timer, the sweep rides the write path.
CREATE TABLE idempotency (
  owner           TEXT        NOT NULL,
  client_token    TEXT        NOT NULL,
  request_digest  TEXT        NOT NULL,
  response_json   JSONB       NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (owner, client_token)
);
CREATE INDEX idempotency_sweep ON idempotency (owner, created_at);
