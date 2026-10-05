-- Privacy mode: a private goal and its whole subtree blur on screen while the owner's mode is on.
-- `rules` are the owner's own words the agent marks goals by.
ALTER TABLE goals ADD COLUMN private BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE privacy_settings (
  owner  TEXT PRIMARY KEY,
  mode   BOOLEAN NOT NULL DEFAULT false,
  rules  TEXT    NOT NULL DEFAULT ''
);

CREATE TRIGGER privacy_settings_change_feed
AFTER INSERT OR UPDATE OR DELETE ON privacy_settings
FOR EACH ROW EXECUTE FUNCTION notify_goals_changed();
