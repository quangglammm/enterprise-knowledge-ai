-- Runs once when the Compose postgres volume is first created.
-- A separate database for integration tests, which truncate tables freely.
CREATE DATABASE eka_test OWNER eka;
