-- verticals/db/migrations/014_docs.sql — documents as first-class residents (D250, KK 2026-08-20,
-- WP-1). Three tables, mirroring the house patterns 001_init.sql and 007_evidence.sql already
-- set: `docs` (the current row per document), `doc_revisions` (append-only full-text history —
-- nothing here ever UPDATEs or DELETEs a revision row; `core/docs.py` enforces that in code, the
-- same stance 007 takes on `goal_evidence`'s payload), and `goal_doc_links` (a derived index over
-- markdown link text, rebuilt from the text on every save — the text is the only truth, this
-- table is a cache of it).
--
-- **The folder tree is just paths.** `docs.path` is `strategy/ai-native.md` — no folder table,
-- no separate directory row; a "folder" is nothing but a shared path prefix, discovered client-
-- side by grouping `tree()`'s flat list on `/`. This mirrors `goals.path`'s own materialized-path
-- shape (001_init.sql) closely enough to reuse the same id scheme (`core/field_rules.generate_id`,
-- 8-char base62) but is NOT a copy of the goals tree: docs carry no `parent_id`/`depth`, because
-- nothing about a doc's own identity depends on its folder — renaming `a/b.md` to `c/b.md` is one
-- `UPDATE ... SET path`, never a subtree rewrite (`core/tree.py`'s whole reason to exist for
-- goals; a doc "subtree" is just every row whose `path` happens to share a prefix, and nothing
-- here needs that to be fast enough to index).
--
-- **Versioning is app-level append-only, deliberately not temporal_tables/pgMemento/git** (KK
-- ruling, docs/EVIDENCE.md's own precedent for "zero extensions, history rides the existing
-- pg_dump" applied here to a second feature). Every `save()` inserts a new `doc_revisions` row
-- and bumps `docs.revision`; `restore()` is spelled as copying an old revision's text forward as
-- a NEW revision, never as rewriting history — so `doc_revisions` truly never needs an `UPDATE`
-- or `DELETE` path, and a plain `pg_dump` already backs the whole feature up.
--
-- `docs_id_owner_unique` exists for exactly the reason `goals_id_owner_unique` does in
-- 007_evidence.sql: `doc_revisions` and `goal_doc_links` both carry a composite FK on
-- `(doc_id, owner)`, and a composite FK needs a UNIQUE constraint on the referenced pair — the
-- bare PK on `id` alone does not provide one. Same trick, same reason: an owner that drifted
-- between a doc and its own revision or link row becomes unrepresentable, not merely unlikely.
--
-- `goal_doc_links.owner` is not redundant with the two FKs it rides on: PostgreSQL composite FKs
-- require every referenced column to be named on both sides, so this table cannot express "this
-- goal and this doc, whichever owners they each have" — it can only express "this goal AND this
-- doc, both belonging to THIS owner", which is exactly codename-law's shape (docs/EVIDENCE.md's
-- FK note makes the identical argument for `goal_evidence`). A link across two different owners'
-- rows is unrepresentable by construction, not refused by application code that could have a bug.
--
-- `source` distinguishes which side's text declared the link — a doc's body linking a goal
-- (`source='doc'`) and a goal's body linking that same doc (`source='goal'`) are two independent
-- facts, not duplicates of one fact, so both can coexist for the same `(goal_id, doc_id)` pair;
-- the PK spans `source` for exactly that reason.
--
-- Forward-only and safe on an empty or populated database (`verticals/db/runner.py` refuses
-- downgrades): three new tables, no rewrite of `goals` or any existing row.

CREATE TABLE docs (
  id          TEXT NOT NULL PRIMARY KEY,
  owner       TEXT NOT NULL,
  path        TEXT NOT NULL,
  title       TEXT,
  body        TEXT NOT NULL DEFAULT '',
  revision    INTEGER NOT NULL DEFAULT 1,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

  CONSTRAINT docs_id_owner_unique UNIQUE (id, owner),
  CONSTRAINT docs_path_unique_per_owner UNIQUE (owner, path)
);

-- `core.docs.tree()`'s own read: every doc for one owner, path order — the index that read
-- wants, and the same index a path-prefix ("folder") scan uses.
CREATE INDEX docs_owner_path ON docs (owner, path);

CREATE TABLE doc_revisions (
  doc_id     TEXT NOT NULL,
  owner      TEXT NOT NULL,
  revision   INTEGER NOT NULL,
  path       TEXT NOT NULL,
  title      TEXT,
  body       TEXT NOT NULL,
  saved_at   TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

  PRIMARY KEY (doc_id, revision),
  FOREIGN KEY (doc_id, owner) REFERENCES docs (id, owner) ON DELETE CASCADE
);

CREATE TABLE goal_doc_links (
  owner    TEXT NOT NULL,
  goal_id  TEXT NOT NULL,
  doc_id   TEXT NOT NULL,
  source   TEXT NOT NULL CHECK (source IN ('doc', 'goal')),

  PRIMARY KEY (owner, goal_id, doc_id, source),
  FOREIGN KEY (goal_id, owner) REFERENCES goals (id, owner) ON DELETE CASCADE,
  FOREIGN KEY (doc_id, owner)  REFERENCES docs  (id, owner) ON DELETE CASCADE
);

-- `core.docs.links_for_doc()`'s own read: every goal linking (or linked from) one doc.
-- `links_for_goal()` rides `goal_doc_links`'s own PK prefix (owner, goal_id, ...) and needs no
-- second index.
CREATE INDEX goal_doc_links_by_doc ON goal_doc_links (owner, doc_id);
