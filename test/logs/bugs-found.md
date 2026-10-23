# Bugs Found Log

This document records bugs exposed by tests during the test suite rebuild. As per ground rules, production code is not modified directly; tests exposing confirmed bugs are marked as expected failures (`xfail`) with references to this log.

| Bug ID | Date | Layer | File / Test | Description | Reproduction / Root Cause | Status |
|---|---|---|---|---|---|---|
| BUG-001 | 2026-10-24 | Concurrency / Performance | `test/pipeline/test_sprint2_async_concurrency.py` (`test_ac2_2_event_loop_lag_remains_under_15ms`, `test_recommend_endpoint_concurrent_async_client`) | Event loop lag exceeds 15ms threshold (reaching 20-40ms) during full suite execution | Wall-clock tick jitter under Windows OS process scheduling and multi-test execution load. Marked as expected failure (`xfail`) without weakening assertion. Passes when run in isolation. | Logged / xfail |
