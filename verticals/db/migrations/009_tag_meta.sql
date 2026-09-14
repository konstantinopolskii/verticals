-- Project-tag metadata. Goal tags remain plain text[]; this registry only changes presentation.
CREATE TABLE tag_meta (
  tag TEXT PRIMARY KEY,
  project BOOLEAN NOT NULL DEFAULT false
);
