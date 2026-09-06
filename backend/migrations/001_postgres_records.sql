-- Non-destructive online persistence foundation.
-- The application stores the same JSON domain documents used by SQLite while
-- deployments migrate incrementally. No local data is copied by this script.
CREATE TABLE IF NOT EXISTS lumina_records (
    namespace TEXT NOT NULL,
    id TEXT NOT NULL,
    owner_email TEXT,
    data_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (namespace, id)
);

CREATE INDEX IF NOT EXISTS idx_lumina_records_owner
    ON lumina_records (owner_email);
