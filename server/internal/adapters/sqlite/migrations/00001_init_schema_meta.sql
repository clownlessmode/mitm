-- +goose Up
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY NOT NULL,
    value TEXT NOT NULL
);

-- +goose Down
DROP TABLE IF EXISTS schema_meta;
