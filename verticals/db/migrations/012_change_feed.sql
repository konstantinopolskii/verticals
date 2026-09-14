-- Change feed (KK, 2026-08-15, D237): the browser follows agent writes live. The API process and
-- the MCP process share exactly one thing — Postgres — so the signal crosses there: an AFTER
-- trigger raises pg_notify('goals_changed', owner) on every goals write, and the API's
-- GET /api/events SSE endpoint LISTENs and forwards one opaque "changed" event to the board.
--
-- The payload is the OWNER, nothing else: the notification is a doorbell, not a data channel.
-- The client refetches the board through the ordinary authenticated route, so nothing readable
-- ever rides the NOTIFY bus and a listener without the bearer token learns only that something
-- changed for an owner id it already had to know.
--
-- FOR EACH ROW, not STATEMENT: the payload needs NEW/OLD.owner. Bursts cost nothing extra —
-- Postgres deduplicates identical (channel, payload) notifications within one transaction, so a
-- 50-row bulk update sends one doorbell.
--
-- due_acknowledgements gets the same trigger: an 'overdue' verdict clears a board ghost without
-- touching goals (011's own design), and the board must follow that too.

CREATE FUNCTION notify_goals_changed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  PERFORM pg_notify('goals_changed', COALESCE(NEW.owner, OLD.owner));
  RETURN NULL;
END;
$$;

CREATE TRIGGER goals_change_feed
AFTER INSERT OR UPDATE OR DELETE ON goals
FOR EACH ROW EXECUTE FUNCTION notify_goals_changed();

CREATE TRIGGER due_ack_change_feed
AFTER INSERT OR UPDATE OR DELETE ON due_acknowledgements
FOR EACH ROW EXECUTE FUNCTION notify_goals_changed();
