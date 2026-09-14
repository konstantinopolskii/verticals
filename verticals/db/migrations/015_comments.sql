-- verticals/db/migrations/015_comments.sql — comments as structured rows (KK decisions
-- 2026-08-25, docs/COMMENTS_SPEC.md, WP-A). Agents are first-class writers of Verticals; a
-- comment thread is the return channel between KK (web UI, `author='human'`) and his agents
-- (MCP, `author='agent'`) — the whole point is that a thread is a ROW an agent can read and
-- answer, never an opaque blob only a browser can render. This is why the kit's own
-- localStorage snapshot shape (`innerHTML`) is refused here (KK's decision 5): two tables,
-- never a document.
--
-- Two tables, mirroring `014_docs.sql`'s own shape one level down: `comment_threads` (the
-- anchor — which goal or doc, and optionally which selected text within it) and
-- `comment_messages` (the append-only conversation inside a thread — never UPDATEd or DELETEd
-- by any code path; v1 has no edit/delete, docs/COMMENTS_SPEC.md's own "Out of scope" list).
--
-- **A thread anchors to exactly one target.** `comment_threads_one_target` is the same XOR
-- shape `comment_threads_id_owner_unique`/composite-FK pairing already uses elsewhere in this
-- schema (`goal_doc_links`, 014) — `(goal_id IS NULL) <> (doc_id IS NULL)` is true for exactly
-- "one NULL, one not", false for "both NULL" and for "neither NULL", which is precisely KK
-- decision 2 ("a thread may anchor to a goal or a doc", never both, never neither). The
-- composite FKs below (`(goal_id, owner)` / `(doc_id, owner)`) are the same trick
-- `014_docs.sql`'s own header comment explains for `goal_doc_links`: a thread whose owner
-- drifted from its target's owner becomes unrepresentable, not merely unlikely, and
-- `comment_threads_id_owner_unique` exists for exactly the reason `docs_id_owner_unique` does
-- one migration over — `comment_messages`'s own composite FK on `(thread_id, owner)` needs a
-- UNIQUE constraint on that referenced pair, which the bare PK on `id` alone does not provide.
--
-- **Anchor trio.** `anchor_quote`/`anchor_prefix`/`anchor_suffix` carry the kit's own
-- quote+prefix+suffix disambiguation shape (KK decision 2, "quote + prefix + suffix, kit-
-- style") for a thread that comments on SELECTED TEXT rather than the whole card/doc. Whether
-- all three are NULL (whole-target thread) or `quote` is NOT NULL (prefix/suffix may still be
-- empty strings, when the selection sits at the very start or end of the body) is a cross-
-- column rule a plain CHECK cannot express as cleanly as `core/comments.py` can (the same call
-- `014_docs.sql`'s own header makes for path validation living in code, not a CHECK) — enforced
-- in `core/comments.py::validate_anchor`, not here.
--
-- **No pg_notify trigger.** `012_change_feed.sql`'s doorbell covers `goals` only; `014_docs.sql`
-- shipped no trigger for `docs` either, and that is the precedent this migration follows, not a
-- new decision — the comment panel refetches on open and after its own writes
-- (docs/COMMENTS_SPEC.md's own WP-A section states this explicitly). A live cross-tab push is a
-- v2 concern, not a WP-A one.
--
-- Forward-only and safe on an empty or populated database (`verticals/db/runner.py` refuses
-- downgrades): two new tables, no rewrite of `goals` or `docs`.

CREATE TABLE comment_threads (
  id          TEXT NOT NULL PRIMARY KEY,
  owner       TEXT NOT NULL,
  goal_id     TEXT,
  doc_id      TEXT,
  anchor_quote  TEXT,
  anchor_prefix TEXT,
  anchor_suffix TEXT,
  resolved_at TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT comment_threads_id_owner_unique UNIQUE (id, owner),
  CONSTRAINT comment_threads_one_target CHECK ((goal_id IS NULL) <> (doc_id IS NULL)),
  FOREIGN KEY (goal_id, owner) REFERENCES goals (id, owner) ON DELETE CASCADE,
  FOREIGN KEY (doc_id, owner)  REFERENCES docs  (id, owner) ON DELETE CASCADE
);

-- `core.comments.list_for_goal`/`list_for_doc`'s own reads: every thread anchored to one goal
-- or one doc, owner-scoped — partial indexes because a row only ever populates one side of the
-- XOR, so the other side's index would carry a 50%-NULL column for nothing (`comment_threads_by_
-- doc` never has to skip a goal-anchored row, and vice versa).
CREATE INDEX comment_threads_by_goal ON comment_threads (owner, goal_id) WHERE goal_id IS NOT NULL;
CREATE INDEX comment_threads_by_doc  ON comment_threads (owner, doc_id)  WHERE doc_id  IS NOT NULL;

-- `core.comments.list_unresolved`'s own read: the agent worklist ("every unresolved thread for
-- the owner"), independent of which target it anchors to — a plain `(owner, resolved_at)`
-- index, not partial, because the predicate this query actually runs (`resolved_at IS NULL`) is
-- the common case for an active board, not the rare one a partial index would be sized for.
CREATE INDEX comment_threads_unresolved ON comment_threads (owner, resolved_at);

CREATE TABLE comment_messages (
  thread_id  TEXT NOT NULL,
  id         TEXT NOT NULL,
  owner      TEXT NOT NULL,
  author     TEXT NOT NULL CHECK (author IN ('human', 'agent')),
  body       TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),

  PRIMARY KEY (thread_id, id),
  FOREIGN KEY (thread_id, owner) REFERENCES comment_threads (id, owner) ON DELETE CASCADE
);
