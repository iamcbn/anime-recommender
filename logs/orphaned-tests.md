# Orphaned and Candidate Stale Tests Log

Observations on test suites and individual test cases noted during the codebase clean-up for future test review.
All tests in this log are preserved untouched per ground rules, unless a test exists solely to exercise code that has been removed.

| Test File | Test Case / Symbol | Observation & Rationale | Status |
| :--- | :--- | :--- | :--- |
| `test/test_api_keys.py` | Entire test module | Requires live PostgreSQL/Supabase database container with migration schemas applied. | Preserved |
| `test/test_sprint1_migration.py` | Entire test module | Requires live PostgreSQL database connection to verify schema DDL migrations. | Preserved |
| `test/test_sprint3_telemetry.py` | Entire test module | Requires active PostgreSQL database instance to test transactional telemetry writes. | Preserved |
| `test/test_telemetry_and_archival.py` | Entire test module | Requires active PostgreSQL database instance to test Parquet export transactions. | Preserved |
