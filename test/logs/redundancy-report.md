# Sprint 1 Test Suite Redundancy Analysis Report

**Sprint**: Sprint 1: Review and Redundancy Analysis
**Branch**: `test-suite-rebuild`
**Date**: 2026-10-23
**Standard**: British English; strict exclusion of em-dashes

---

## 1. Executive Summary

This report delivers the comprehensive review and redundancy analysis of all test files, test methods, research experiments, offline evaluation pipelines, and live probes in the `test/` directory. Each test item has been individually examined against the strict criteria for pruning and consolidation.

A total of 426 items were analysed across 30 files, comprising 419 automated pytest items and 7 standalone scripts/benchmarks. The analysis identifies substantial redundancy, primarily driven by:
1. **Static AST and regular expression matching masquerading as frontend tests**: 63 tests across four files inspect TypeScript and TSX files as static text rather than executing JavaScript runtime assertions, providing no genuine behavioural coverage.
2. **Redundant security and authentication assertions**: Multiple test files implement duplicate JWT generation, duplicate mock JWKS services, duplicate secret scanning routines, and duplicate rate limit assertion loops.
3. **Subsumed unit and integration tests**: Broader end-to-end tests and canonical smoke tests fully subsume narrow duplicate tests across pipeline modules.
4. **Orphaned research scripts and live probes**: Benchmark and experiment scripts relying on nonexistent datasets or calling live external APIs outside automated test discovery.

---

## 2. Overall Totals and Metrics

### 2.1 Grand Totals (All Reviewed Items)

| Classification | Count | Percentage | Description |
|---|---|---|---|
| **KEEP** | 277 | 65.02% | Essential tests providing unique branch, error path, or security verification |
| **KEEP (FLAGGED)** | 5 | 1.17% | Retained tests that warrant attention (e.g. tracer overhead sensitivity or environment dependence) |
| **MERGE** | 60 | 14.08% | Near-duplicates or narrow tests to be consolidated into parent/parameterised suites |
| **DELETE** | 84 | 19.72% | Obsolete, subsumed, static string-matching, dead scripts, or live probes |
| **TOTAL** | **426** | **100.0%** | Complete inventory of reviewed test items and scripts |

### 2.2 Automated Pytest Suite Breakdown (419 Items)

* **KEEP / KEEP (FLAGGED)**: 282 tests (67.30%)
* **MERGE**: 60 tests (14.32%)
* **DELETE**: 77 tests (18.38%)

### 2.3 Standalone Scripts, Benchmarks, and Probes (7 Items)

* **DELETE**: 7 scripts (100.0% - to be removed from test runner discovery or relocated to operational tooling)

---

## 3. Redundancy and Non-Redundancy Criteria

### 3.1 Redundancy Definition
A test is classified as **DELETE** or **MERGE** if it satisfies any of the following conditions:
* **Exact or near duplicate**: Verifies identical logic with identical assertions across multiple test files.
* **Fully subsumed**: Covered entirely by a broader unit, integration, or smoke test.
* **No meaningful runtime assertions**: Verifies framework internals, tests only whether a mock was invoked, or checks static file existence (os.path.isfile).
* **Static text inspection of frontend code**: Inspects TypeScript/TSX components via regex string searches instead of native component rendering.
* **Permanently broken, dead, or missing assets**: Relies on deleted datasets or superseded module implementations.
* **Live probe or manual experiment**: Non-automated scripts intended for ad-hoc benchmarking or live API monitoring.

### 3.2 Non-Redundancy Definition
A test is classified as **KEEP** if it satisfies any of the following conditions:
* **Unique branch or error path**: Exercises code paths not touched by any other test.
* **Tied to past bug, security hardening, or acceptance criteria**: Directly validates regression defenses or compliance gates.
* **Core smoke and isolation foundation**: Hermetic unit and smoke tests providing foundational reliability.
* **KEEP (FLAGGED)**: Assigned when retention is recommended but execution latency, coverage tracer sensitivity, or external dependencies require refinement during Sprint 2.

---

## 4. File-by-File Summary Tables

### 4.1 test/hourly_run.py

*Total Items:* 1 | *KEEP:* 0 | *MERGE:* 0 | *DELETE:* 1

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/hourly_run.py | hourly_run.py | **DELETE** | Live synthetic query probe calling external Gemini and Modal APIs outside standard automated test execution. |

### 4.2 test/benchmarks/SBERT_TEST.py

*Total Items:* 1 | *KEEP:* 0 | *MERGE:* 0 | *DELETE:* 1

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/benchmarks/SBERT_TEST.py | SBERT_TEST.py | **DELETE** | Orphaned historical SentenceTransformer benchmark relying on nonexistent Excel dataset anilist_anime_data_complete.xlsx. |

### 4.3 test/experiments/compare_embeddings.py

*Total Items:* 1 | *KEEP:* 0 | *MERGE:* 0 | *DELETE:* 1

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/experiments/compare_embeddings.py | compare_embeddings.py | **DELETE** | Offline exploratory research script comparing MiniLM and BGE-Small embeddings against live database outside automated testing. |

### 4.4 test/experiments/experiment_k.py

*Total Items:* 1 | *KEEP:* 0 | *MERGE:* 0 | *DELETE:* 1

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/experiments/experiment_k.py | experiment_k.py | **DELETE** | Offline parameter sweep script evaluating RRF constant k values outside automated testing. |

### 4.5 test/pipeline/evaluate_first_stage.py

*Total Items:* 1 | *KEEP:* 0 | *MERGE:* 0 | *DELETE:* 1

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/evaluate_first_stage.py | evaluate_first_stage.py | **DELETE** | Offline evaluation pipeline runner driving retrieval and cross-encoder outside standard automated test discovery. |

### 4.6 test/pipeline/evaluate_pipeline.py

*Total Items:* 1 | *KEEP:* 0 | *MERGE:* 0 | *DELETE:* 1

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/evaluate_pipeline.py | evaluate_pipeline.py | **DELETE** | Offline metric calculation script computing Hit Rate and MRR from JSONL outside automated testing. |

### 4.7 test/pipeline/generate_report.py

*Total Items:* 1 | *KEEP:* 0 | *MERGE:* 0 | *DELETE:* 1

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/generate_report.py | generate_report.py | **DELETE** | Markdown report generation script producing evaluation_report_v2.md outside automated testing. |

### 4.8 test/smoke/test_isolated_smoke.py

*Total Items:* 46 | *KEEP:* 44 | *MERGE:* 2 | *DELETE:* 0

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/smoke/test_isolated_smoke.py | TestIsolationFixturesAndMocks::test_llm_cache_isolated_crud | **KEEP** | Unique branch verifying isolated temporary SQLite CRUD operations for HyDE caching. |
| test/smoke/test_isolated_smoke.py | TestIsolationFixturesAndMocks::test_llm_cache_disabled_flag | **KEEP** | Unique branch verifying that DISABLE_LLM_CACHE flag renders cache completely inactive. |
| test/smoke/test_isolated_smoke.py | TestIsolationFixturesAndMocks::test_database_manager_pool_saturation_and_vitality | **KEEP** | Verifies DatabaseManager pool checkout timeout and vitality in isolation. |
| test/smoke/test_isolated_smoke.py | TestGetRootEndpoint::test_get_root_returns_200_and_welcome_message | **KEEP** | Fast smoke check verifying root health endpoint status and canonical payload. |
| test/smoke/test_isolated_smoke.py | TestPostRecommendSuccess::test_post_recommend_returns_200_valid_schema | **KEEP** | Verifies baseline POST /recommend contract and public score stripping. |
| test/smoke/test_isolated_smoke.py | TestPostRecommendAuthentication::test_post_recommend_missing_api_key_returns_403 | **KEEP** | Verifies 403 response on missing authentication header. |
| test/smoke/test_isolated_smoke.py | TestPostRecommendAuthentication::test_post_recommend_invalid_api_key_returns_403 | **KEEP** | Verifies rejection of invalid or unknown API key. |
| test/smoke/test_isolated_smoke.py | TestPostRecommendValidation::test_post_recommend_query_too_short_returns_422 | **KEEP** | Verifies Pydantic min_length validation failure on short input. |
| test/smoke/test_isolated_smoke.py | TestPostRecommendValidation::test_post_recommend_empty_query_returns_422 | **MERGE** | Subsumed by test_post_recommend_query_too_short_returns_422; consolidate into single payload validation test. |
| test/smoke/test_isolated_smoke.py | TestPostRecommendValidation::test_post_recommend_missing_query_field_returns_422 | **MERGE** | Subsumed by test_post_recommend_query_too_short_returns_422; consolidate into single payload validation test. |
| test/smoke/test_isolated_smoke.py | TestPostRecommendRateLimiter::test_rate_limiter_logic_unit | **KEEP** | Fast unit test verifying sliding-window quota calculation logic. |
| test/smoke/test_isolated_smoke.py | TestPostRecommendRateLimiter::test_post_recommend_rate_limiter_triggers_429 | **KEEP** | Integration smoke test verifying HTTP 429 response when quota is exhausted. |
| test/smoke/test_isolated_smoke.py | TestAsyncRagPipelineSmoke::test_async_rag_pipeline_execution_and_timings | **KEEP** | Canonical isolated async pipeline smoke verifying candidate results and timing keys. |
| test/smoke/test_isolated_smoke.py | TestAsyncRagPipelineSmoke::test_async_rag_pipeline_via_inference_client_path | **KEEP** | Covers dedicated async inference client dispatch path. |
| test/smoke/test_isolated_smoke.py | TestSyncRagPipelineSmoke::test_sync_rag_pipeline_execution_and_timings | **KEEP** | Canonical isolated sync pipeline smoke verifying backward compatibility. |
| test/smoke/test_isolated_smoke.py | TestSyncRagPipelineSmoke::test_sync_rag_pipeline_via_inference_client_path | **KEEP** | Covers dedicated sync inference client dispatch path. |
| test/smoke/test_isolated_smoke.py | TestQueryGeneratorSmoke::test_generate_async_success | **KEEP** | Verifies asynchronous HyDE query generation using OpenAI parser. |
| test/smoke/test_isolated_smoke.py | TestQueryGeneratorSmoke::test_generate_async_fallback_on_exception | **KEEP** | Verifies graceful fallback to raw query on asynchronous OpenAI timeout. |
| test/smoke/test_isolated_smoke.py | TestQueryGeneratorSmoke::test_generate_sync_success | **KEEP** | Verifies synchronous HyDE query generation using OpenAI parser. |
| test/smoke/test_isolated_smoke.py | TestQueryGeneratorSmoke::test_generate_sync_fallback_on_exception | **KEEP** | Verifies graceful fallback to raw query on synchronous OpenAI exception. |
| test/smoke/test_isolated_smoke.py | TestQueryGeneratorSmoke::test_generate_cache_hit_bypasses_openai | **KEEP** | Verifies cache hit avoids invocation of OpenAI client. |
| test/smoke/test_isolated_smoke.py | TestQueryGeneratorSmoke::test_query_generator_requires_api_key | **KEEP** | Verifies environment validation requiring OpenAI API key. |
| test/smoke/test_isolated_smoke.py | TestInferenceClientsSmoke::test_factory_get_inference_client_resolution | **KEEP** | Verifies client resolution between LocalInferenceClient and ModalInferenceClient. |
| test/smoke/test_isolated_smoke.py | TestInferenceClientsSmoke::test_local_inference_client_execution | **KEEP** | Covers sync and async execution paths on LocalInferenceClient. |
| test/smoke/test_isolated_smoke.py | TestInferenceClientsSmoke::test_modal_inference_client_remote_and_fallback | **KEEP** | Covers Modal RPC execution and fallback to local inference on failure. |
| test/smoke/test_isolated_smoke.py | TestInferenceClientsSmoke::test_sanitize_candidates_for_rpc | **KEEP** | Verifies stripping of heavy fields prior to Modal RPC transport. |
| test/smoke/test_isolated_smoke.py | TestModalDeploySmoke::test_modal_deploy_app_and_worker_interface | **KEEP** | Validates Modal deployment worker actor definitions and entrypoints. |
| test/smoke/test_isolated_smoke.py | TestSprint1HardeningSmoke::test_ddl_decoupled_from_server_startup_ac1_2 | **KEEP** | Critical acceptance check verifying server import does not run DDL. |
| test/smoke/test_isolated_smoke.py | TestSprint1HardeningSmoke::test_candidate_metadata_enrichment_preservation_ac1_3 | **KEEP** | Critical acceptance check verifying metadata preservation across pipeline steps. |
| test/smoke/test_isolated_smoke.py | TestSprint1HardeningSmoke::test_database_config_default_port_detection_ac1_1 | **KEEP** | Critical acceptance check verifying port detection for PgBouncer pooler. |
| test/smoke/test_isolated_smoke.py | TestSprint3GuardrailsSmoke::test_guardrails_latency_under_15ms_ac3_2 | **KEEP** | Fast smoke check ensuring pre-retrieval validation executes in under 15ms. |
| test/smoke/test_isolated_smoke.py | TestSprint3GuardrailsSmoke::test_guardrails_blocks_prompt_injections_and_out_of_scope | **KEEP** | Smoke verification blocking prompt injections and out-of-scope tasks. |
| test/smoke/test_isolated_smoke.py | TestSprint3GuardrailsSmoke::test_guardrails_zero_false_positives_on_anime_queries | **KEEP** | Smoke verification ensuring zero false positives on genuine anime queries. |
| test/smoke/test_isolated_smoke.py | TestSprint3GuardrailsSmoke::test_active_spoiler_scrubber | **KEEP** | Smoke verification redacting plot twists while keeping premises intact. |
| test/smoke/test_isolated_smoke.py | TestSprint3GuardrailsSmoke::test_confidence_assessment_boundary | **KEEP** | Smoke verification for cross-encoder score boundary at -6.5. |
| test/smoke/test_isolated_smoke.py | TestSprint3DualStreamSSESmoke::test_post_chat_sse_metadata_and_token_streaming_ac3_1 | **KEEP** | Fast smoke test for dual-stream SSE emission and card delivery. |
| test/smoke/test_isolated_smoke.py | TestSprint3DualStreamSSESmoke::test_post_chat_guardrail_rejection_ac3_2 | **KEEP** | Fast smoke test for immediate SSE error event on invalid prompt. |
| test/smoke/test_isolated_smoke.py | TestSprint3DualStreamSSESmoke::test_post_chat_openai_500_circuit_breaker_preserves_cards_ac3_3 | **KEEP** | Fast smoke test verifying circuit breaker fallback delivers cards during OpenAI outage. |
| test/smoke/test_isolated_smoke.py | TestSprint4StateManagerSmoke::test_state_manager_multi_turn_history_and_rolling_eviction_ac4_1 | **KEEP** | Fast smoke test for rolling 5-turn session eviction. |
| test/smoke/test_isolated_smoke.py | TestSprint4StateManagerSmoke::test_state_manager_in_memory_fallback_on_unconfigured_or_timeout | **KEEP** | Fast smoke test for StateManager fallback when Redis is unconfigured. |
| test/smoke/test_isolated_smoke.py | TestSprint4ExclusionFilteringSmoke::test_seen_ids_exclusion_zero_recurrence_ac4_2 | **KEEP** | Fast smoke test verifying exclusion of seen anime IDs. |
| test/smoke/test_isolated_smoke.py | TestSprint4ExclusionFilteringSmoke::test_seen_ids_subtraction_all_candidates_seen | **KEEP** | Edge-case smoke test when 100% of candidates have already been seen. |
| test/smoke/test_isolated_smoke.py | TestSprint4DistributedRateLimiterSmoke::test_distributed_sliding_window_rate_limiting_ac4_3 | **KEEP** | Fast smoke test for distributed sliding window limit trigger. |
| test/smoke/test_isolated_smoke.py | TestSprint4DistributedRateLimiterSmoke::test_rate_limiter_rfc6585_headers_on_429 | **KEEP** | Fast smoke test verifying RFC 6585 headers in 429 response. |
| test/smoke/test_isolated_smoke.py | TestSprint4DistributedRateLimiterSmoke::test_rate_limiter_dual_mode_compatibility | **KEEP** | Unit verification of sync unpacking and async await dual-mode result. |
| test/smoke/test_isolated_smoke.py | TestSprint4WebChatSessionSmoke::test_web_chat_multi_turn_session_flow_ac4_4 | **KEEP** | Fast smoke test for multi-turn web chat session SSE flow. |

### 4.9 test/pipeline/test_guardrails.py

*Total Items:* 28 | *KEEP:* 27 | *MERGE:* 1 | *DELETE:* 0

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_ac3_2_pre_retrieval_validation_latency_benchmark | **KEEP** | Rigorous 1,000-iteration performance micro-benchmark verifying latency under 15ms. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_rejects_instruction_override | **KEEP** | Comprehensive security test rejecting direct system instruction overrides. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_rejects_system_prompt_leaks | **KEEP** | Comprehensive security test rejecting system prompt extraction attempts. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_rejects_jailbreak_modes | **KEEP** | Security test rejecting DAN and uncensored developer persona jailbreaks. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_rejects_delimiter_and_template_injections | **KEEP** | Security test rejecting delimiter and template token manipulation attacks. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_rejects_hybrid_adversarial_queries | **KEEP** | Security test rejecting adversarial injection payloads embedded in benign queries. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_rejects_out_of_scope_coding | **KEEP** | Domain boundary test rejecting programming and code generation requests. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_rejects_out_of_scope_math | **KEEP** | Domain boundary test rejecting mathematical equation solving. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_rejects_out_of_scope_politics | **KEEP** | Domain boundary test rejecting real-world political queries. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_rejects_out_of_scope_crypto_and_finance | **KEEP** | Domain boundary test rejecting financial trading queries. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_rejects_out_of_scope_general | **KEEP** | Domain boundary test rejecting weather and cooking queries. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_rejects_empty_and_excessive_queries | **KEEP** | Input boundary test rejecting empty queries and excessive string lengths. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_zero_false_positives_on_protected_titles | **KEEP** | Critical regression test preserving access to titles containing sensitive keywords like Code Geass. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_zero_false_positives_on_narrative_queries_with_trigger_words | **KEEP** | Regression test ensuring anime queries with trigger words like hackers or python are permitted. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_tuple_unpacking_compatibility | **KEEP** | Unit contract check for GuardrailResult tuple unpacking. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_confidence_assessment_high_confidence | **KEEP** | Unit verification of high confidence score assessment. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_confidence_assessment_boundary | **KEEP** | Unit verification of the -6.5 boundary score threshold. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_confidence_assessment_low_confidence_triggers_fallback | **KEEP** | Verifies that low scores trigger fallback recommendation flag. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_confidence_assessment_empty_candidates | **KEEP** | Edge-case test handling empty candidate list in confidence evaluator. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_confidence_assessment_with_pandas_dataframe | **MERGE** | Subsumed by test_confidence_assessment_high_confidence; merge into single parameterised input test. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_canonical_fallback_recommendations | **KEEP** | Verifies structure and content of canonical fallback recommendations. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_scrubs_character_climax_deaths | **KEEP** | Post-retrieval spoiler scrubber test for character deaths. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_scrubs_unmasking_of_killers_and_villains | **KEEP** | Post-retrieval spoiler scrubber test for killer/traitor reveals. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_scrubs_true_identity_reveals | **KEEP** | Post-retrieval spoiler scrubber test for secret identity reveals. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_scrubs_explicit_spoiler_tags | **KEEP** | Post-retrieval spoiler scrubber test for explicit tag formats. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_preserves_markdown_formatting | **KEEP** | Verifies formatting preservation when scrubbing spoilers from text. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_zero_corruption_on_normal_premises_and_synopses | **KEEP** | Regression protection ensuring spoiler scrubber does not corrupt normal synopses. |
| test/pipeline/test_guardrails.py | TestDomainGuardrails::test_streaming_chunk_scrubber | **KEEP** | Unit verification of chunk boundary buffering in streaming spoiler scrubber. |

### 4.10 test/pipeline/test_sprint10_citations.py

*Total Items:* 19 | *KEEP:* 16 | *MERGE:* 3 | *DELETE:* 0

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/test_sprint10_citations.py | TestCitationValidationAndSanitization::test_valid_candidate_id_preserved | **KEEP** | Verifies preservation of valid candidate citations in generated commentary. |
| test/pipeline/test_sprint10_citations.py | TestCitationValidationAndSanitization::test_invalid_hallucinated_candidate_id_stripped | **KEEP** | Security test stripping hallucinated anime IDs from commentary tags. |
| test/pipeline/test_sprint10_citations.py | TestCitationValidationAndSanitization::test_multiple_tags_mixed_valid_and_invalid | **KEEP** | Verifies handling of mixed valid and invalid citation tags. |
| test/pipeline/test_sprint10_citations.py | TestCitationValidationAndSanitization::test_empty_string_and_falsy_inputs | **KEEP** | Boundary test for empty or null commentary strings. |
| test/pipeline/test_sprint10_citations.py | TestCitationValidationAndSanitization::test_coerces_mixed_id_types_gracefully | **KEEP** | Unit test handling integer and string candidate IDs. |
| test/pipeline/test_sprint10_citations.py | TestStreamingCitationBuffer::test_chunk_split_across_valid_tag_boundary | **KEEP** | Verifies streaming buffer reassembly when tag splits across chunks. |
| test/pipeline/test_sprint10_citations.py | TestStreamingCitationBuffer::test_chunk_split_across_invalid_tag_boundary | **KEEP** | Verifies streaming buffer drops hallucinated tags split across chunks. |
| test/pipeline/test_sprint10_citations.py | TestStreamingCitationBuffer::test_single_character_streaming_fragmentation | **KEEP** | Stress test validating buffer integrity under 1-character streaming fragmentation. |
| test/pipeline/test_sprint10_citations.py | TestStreamingCitationBuffer::test_split_at_bracket_boundary | **MERGE** | Subsumed by test_chunk_split_across_valid_tag_boundary; consolidate bracket split cases. |
| test/pipeline/test_sprint10_citations.py | TestStreamingCitationBuffer::test_normal_text_with_brackets_no_hanging_or_leak | **KEEP** | Verifies non-citation brackets are emitted without hanging the stream. |
| test/pipeline/test_sprint10_citations.py | TestStreamingCitationBuffer::test_metadata_brackets_no_hanging | **MERGE** | Subsumed by test_normal_text_with_brackets_no_hanging_or_leak. |
| test/pipeline/test_sprint10_citations.py | TestStreamingCitationBuffer::test_unclosed_trailing_bracket_flushes_at_end | **KEEP** | Edge-case test ensuring unclosed trailing brackets flush on stream termination. |
| test/pipeline/test_sprint10_citations.py | TestStreamingCitationBuffer::test_non_anime_double_brackets | **MERGE** | Subsumed by test_normal_text_with_brackets_no_hanging_or_leak. |
| test/pipeline/test_sprint10_citations.py | TestStreamingCitationBuffer::test_alias_equivalence | **KEEP** | Verifies citation parser recognizes configured tag aliases. |
| test/pipeline/test_sprint10_citations.py | TestPromptFormattingAndCitations::test_candidate_prompt_formatting_includes_id | **KEEP** | Verifies prompt construction includes candidate IDs for citation grounding. |
| test/pipeline/test_sprint10_citations.py | TestPromptFormattingAndCitations::test_system_prompt_instructs_structured_citations | **KEEP** | Verifies system prompt enforces citation syntax rules. |
| test/pipeline/test_sprint10_citations.py | TestPromptFormattingAndCitations::test_deterministic_fallback_pitch_includes_valid_tags | **KEEP** | Verifies deterministic fallback pitch adheres to citation tag format. |
| test/pipeline/test_sprint10_citations.py | TestOrchestratorCitationIntegration::test_orchestrator_stream_chat_preserves_valid_and_strips_hallucinated_tags | **KEEP** | Orchestrator integration test validating citation sanitization in stream. |
| test/pipeline/test_sprint10_citations.py | TestOrchestratorCitationIntegration::test_synthesizer_stream_dual_sse_validates_citations | **KEEP** | Synthesizer integration test validating SSE token stream sanitization. |

### 4.11 test/pipeline/test_sprint11_admin_usage.py

*Total Items:* 18 | *KEEP:* 13 | *MERGE:* 1 | *DELETE:* 4

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/test_sprint11_admin_usage.py | test_cost_formula_calculation | **KEEP** | Unit verification of standard gpt-5.4-mini pricing calculation. |
| test/pipeline/test_sprint11_admin_usage.py | test_auth_unauthenticated_requests | **KEEP** | Security check enforcing 401 on unauthenticated admin usage requests. |
| test/pipeline/test_sprint11_admin_usage.py | test_auth_invalid_token | **KEEP** | Security check enforcing 401 on invalid JWT tokens. |
| test/pipeline/test_sprint11_admin_usage.py | test_auth_non_admin_jwt_forbidden | **KEEP** | Security check enforcing 403 when non-admin JWT accesses usage endpoint. |
| test/pipeline/test_sprint11_admin_usage.py | test_auth_admin_jwt_success | **KEEP** | Verifies 200 OK when authenticated admin JWT accesses usage endpoint. |
| test/pipeline/test_sprint11_admin_usage.py | test_auth_admin_api_key_env_success | **KEEP** | Verifies access granted via breakglass ADMIN_API_KEY environment variable. |
| test/pipeline/test_sprint11_admin_usage.py | test_auth_admin_api_key_db_lookup | **KEEP** | Verifies access granted via admin API key looked up from database. |
| test/pipeline/test_sprint11_admin_usage.py | test_auth_non_admin_api_key_db_lookup | **KEEP** | Verifies 403 Forbidden when standard API key attempts admin usage access. |
| test/pipeline/test_sprint11_admin_usage.py | test_daily_usage_aggregation_and_formatting | **KEEP** | Contract verification for GET /admin/llm-usage/daily aggregations. |
| test/pipeline/test_sprint11_admin_usage.py | test_daily_usage_layer_filtering | **KEEP** | Verifies SQL query filtering by layer parameter. |
| test/pipeline/test_sprint11_admin_usage.py | test_daily_usage_graceful_database_fallback | **KEEP** | Resilience verification returning empty list when telemetry table is missing. |
| test/pipeline/test_sprint11_admin_usage.py | test_current_budget_default_status | **KEEP** | Contract verification for GET /admin/llm-usage/current-budget structure. |
| test/pipeline/test_sprint11_admin_usage.py | test_current_budget_soft_and_hard_limit_triggers | **KEEP** | Verifies soft 80% and hard 100% budget limit status flags. |
| test/pipeline/test_sprint11_admin_usage.py | TestFrontendSprint11Architecture::test_frontend_files_exist | **DELETE** | Redundant file existence check checking os.path.isfile without runtime assertions. |
| test/pipeline/test_sprint11_admin_usage.py | TestFrontendSprint11Architecture::test_use_llm_usage_hook_contract | **DELETE** | Static regex string search on TypeScript file; to be replaced by native Vitest test. |
| test/pipeline/test_sprint11_admin_usage.py | TestFrontendSprint11Architecture::test_llm_usage_view_contract | **DELETE** | Static regex string search on React view file; to be replaced by native Vitest test. |
| test/pipeline/test_sprint11_admin_usage.py | TestFrontendSprint11Architecture::test_app_and_navbar_routing | **DELETE** | Static regex string search on TypeScript routing file; to be replaced by native Vitest test. |
| test/pipeline/test_sprint11_admin_usage.py | TestFrontendSprint11Architecture::test_zero_secrets_in_frontend | **MERGE** | Subsumed by central frontend secret audit test in test_sprint6_security_rls.py. |

### 4.12 test/pipeline/test_sprint11_budget_guard.py

*Total Items:* 17 | *KEEP:* 12 | *MERGE:* 5 | *DELETE:* 0

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/test_sprint11_budget_guard.py | TestBudgetKeyFormatting::test_key_structure_with_explicit_date | **KEEP** | Unit verification of Redis token budget key naming structure. |
| test/pipeline/test_sprint11_budget_guard.py | TestBudgetKeyFormatting::test_key_structure_defaults_to_utc_today | **MERGE** | Subsumed by test_key_structure_with_explicit_date; consolidate into parameterised test. |
| test/pipeline/test_sprint11_budget_guard.py | TestBudgetKeyFormatting::test_invalid_layer_raises_value_error | **KEEP** | Unit verification rejecting invalid pipeline layer identifier. |
| test/pipeline/test_sprint11_budget_guard.py | TestAtomicIncrementAndUsageTracking::test_atomic_increment_in_memory | **KEEP** | Unit verification of atomic in-memory token increment and tracking. |
| test/pipeline/test_sprint11_budget_guard.py | TestAtomicIncrementAndUsageTracking::test_per_layer_isolation | **KEEP** | Verifies token counters maintain strict per-layer isolation. |
| test/pipeline/test_sprint11_budget_guard.py | TestAtomicIncrementAndUsageTracking::test_date_isolation | **KEEP** | Verifies token counters maintain daily isolation across UTC dates. |
| test/pipeline/test_sprint11_budget_guard.py | TestAtomicIncrementAndUsageTracking::test_check_budget_status_details | **KEEP** | Contract verification for detailed budget status dictionary. |
| test/pipeline/test_sprint11_budget_guard.py | TestSoftAndHardLimits::test_soft_limit_warning_trigger | **KEEP** | Verifies soft alert triggers at 80% token consumption ceiling. |
| test/pipeline/test_sprint11_budget_guard.py | TestSoftAndHardLimits::test_hard_limit_ceiling_trigger | **KEEP** | Verifies hard ceiling triggers at 100% token consumption ceiling. |
| test/pipeline/test_sprint11_budget_guard.py | TestNLIGracefulDegradation::test_nli_parser_bypasses_llm_when_budget_exceeded | **KEEP** | Unit verification that NLIParser skips LLM call when budget exceeded. |
| test/pipeline/test_sprint11_budget_guard.py | TestNLIGracefulDegradation::test_orchestrator_bypasses_nli_when_budget_exceeded | **MERGE** | Subsumed by test_sprint11_smoke.py::test_nli_budget_exhaustion_degrades_to_raw_query. |
| test/pipeline/test_sprint11_budget_guard.py | TestRetrievalGracefulDegradation::test_query_generator_skips_hyde_when_budget_exceeded | **MERGE** | Subsumed by test_sprint11_smoke.py::test_retrieval_budget_exhaustion_skips_hyde. |
| test/pipeline/test_sprint11_budget_guard.py | TestPresentationGracefulDegradation::test_synthesizer_yields_fallback_pitch_when_budget_exceeded | **MERGE** | Subsumed by test_sprint11_smoke.py::test_presentation_budget_exhaustion_serves_deterministic_fallback. |
| test/pipeline/test_sprint11_budget_guard.py | TestPresentationGracefulDegradation::test_orchestrator_presentation_degradation_delivers_cards_and_fallback | **KEEP** | Verifies orchestrator delivers candidate cards alongside fallback pitch. |
| test/pipeline/test_sprint11_budget_guard.py | TestRedisResilienceAndTimeoutFallback::test_redis_timeout_activates_fallback_without_raising | **KEEP** | Verifies budget guard activates fallback on Redis timeout without raising exception. |
| test/pipeline/test_sprint11_budget_guard.py | TestRedisResilienceAndTimeoutFallback::test_redis_connection_error_activates_fallback_without_raising | **MERGE** | Subsumed by test_redis_timeout_activates_fallback_without_raising; merge Redis error cases. |
| test/pipeline/test_sprint11_budget_guard.py | TestRedisResilienceAndTimeoutFallback::test_redis_atomic_increment_and_ttl_set | **KEEP** | Verifies Redis atomic increment Lua script execution and TTL setting. |

### 4.13 test/pipeline/test_sprint11_smoke.py

*Total Items:* 15 | *KEEP:* 10 | *MERGE:* 5 | *DELETE:* 0

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/test_sprint11_smoke.py | TestModalDeploymentReadiness::test_modal_gateway_secrets_with_per_layer_isolation | **KEEP** | Verifies Modal gateway secret mapping when per-layer isolation is enabled. |
| test/pipeline/test_sprint11_smoke.py | TestModalDeploymentReadiness::test_modal_gateway_secrets_fallback_to_shared_secret | **KEEP** | Verifies Modal gateway fallback to shared secret when per-layer isolation is disabled. |
| test/pipeline/test_sprint11_smoke.py | TestModalDeploymentReadiness::test_modal_gateway_secrets_env_variable_control | **MERGE** | Subsumed by test_modal_gateway_secrets_with_per_layer_isolation; consolidate environment toggle tests. |
| test/pipeline/test_sprint11_smoke.py | TestModalDeploymentReadiness::test_modal_app_and_worker_config | **MERGE** | Duplicate of test_isolated_smoke.py::test_modal_deploy_app_and_worker_interface. |
| test/pipeline/test_sprint11_smoke.py | TestConsumerDiscoveryEndToEndStream::test_full_sse_chat_stream_candidate_cards_and_pitch | **KEEP** | Comprehensive end-to-end smoke test validating full SSE chat stream. |
| test/pipeline/test_sprint11_smoke.py | TestGracefulDegradationUnderTokenCeilings::test_nli_budget_exhaustion_degrades_to_raw_query | **KEEP** | End-to-end verification of NLI bypass under budget ceiling. |
| test/pipeline/test_sprint11_smoke.py | TestGracefulDegradationUnderTokenCeilings::test_retrieval_budget_exhaustion_skips_hyde | **KEEP** | End-to-end verification of HyDE skip under budget ceiling. |
| test/pipeline/test_sprint11_smoke.py | TestGracefulDegradationUnderTokenCeilings::test_presentation_budget_exhaustion_serves_deterministic_fallback | **KEEP** | End-to-end verification of fallback pitch under presentation ceiling. |
| test/pipeline/test_sprint11_smoke.py | TestGracefulDegradationUnderTokenCeilings::test_tri_layer_budget_exhaustion_100_percent_uptime_zero_tokens | **KEEP** | Critical acceptance test demonstrating 100% uptime with zero tokens consumed across all layers. |
| test/pipeline/test_sprint11_smoke.py | TestAdminUsageExplorerEndpoints::test_admin_llm_usage_endpoints_auth_enforcement | **MERGE** | Subsumed by detailed auth matrix in test_sprint11_admin_usage.py. |
| test/pipeline/test_sprint11_smoke.py | TestAdminUsageExplorerEndpoints::test_admin_llm_usage_current_budget_success | **MERGE** | Subsumed by test_sprint11_admin_usage.py::test_current_budget_default_status. |
| test/pipeline/test_sprint11_smoke.py | TestAdminUsageExplorerEndpoints::test_admin_llm_usage_daily_success_and_cost_accuracy | **MERGE** | Subsumed by test_sprint11_admin_usage.py::test_daily_usage_aggregation_and_formatting. |
| test/pipeline/test_sprint11_smoke.py | TestSecretRedactionAndLogIsolation::test_secret_redaction_regexes | **KEEP** | Unit verification of central secret redaction regex patterns. |
| test/pipeline/test_sprint11_smoke.py | TestSecretRedactionAndLogIsolation::test_error_response_secret_redaction | **KEEP** | Security test ensuring API error responses never leak API keys or Bearer tokens. |
| test/pipeline/test_sprint11_smoke.py | TestSecretRedactionAndLogIsolation::test_log_sanitization_helper | **KEEP** | Security test ensuring log sanitizer redacts credentials before emission. |

### 4.14 test/pipeline/test_sprint1_hardening.py

*Total Items:* 9 | *KEEP:* 6 | *MERGE:* 3 | *DELETE:* 0

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/test_sprint1_hardening.py | TestSprint1Hardening::test_ac1_1_pool_saturation_and_timeout | **KEEP** | Simulates PostgreSQL connection pool saturation and timeout recovery. |
| test/pipeline/test_sprint1_hardening.py | TestSprint1Hardening::test_ac1_1_pool_saturation_recovers_when_connection_released | **KEEP** | Verifies connection pool recovery when a held connection is released. |
| test/pipeline/test_sprint1_hardening.py | TestSprint1Hardening::test_ac1_1_putconn_closes_broken_connection | **KEEP** | Verifies broken or dead connections are closed rather than returned to pool. |
| test/pipeline/test_sprint1_hardening.py | TestSprint1Hardening::test_ac1_2_import_rag_pipeline_does_not_execute_ddl | **MERGE** | Subsumed by test_isolated_smoke.py::test_ddl_decoupled_from_server_startup_ac1_2. |
| test/pipeline/test_sprint1_hardening.py | TestSprint1Hardening::test_ac1_3_json_conversion_backward_compatibility_when_flag_false | **MERGE** | Consolidate with test_ac1_3_json_conversion_includes_metadata_when_flag_true into single parameterised test. |
| test/pipeline/test_sprint1_hardening.py | TestSprint1Hardening::test_ac1_3_json_conversion_includes_metadata_when_flag_true | **KEEP** | Acceptance test verifying rich candidate metadata is preserved across serialisation. |
| test/pipeline/test_sprint1_hardening.py | TestSprint1Hardening::test_seen_ids_set_subtraction_excludes_specified_anime | **KEEP** | Unit test verifying seen anime IDs are excluded from recommendation candidates. |
| test/pipeline/test_sprint1_hardening.py | TestSprint1Hardening::test_seen_ids_subtraction_when_all_candidates_seen | **KEEP** | Edge-case test handling empty output when 100% of candidates have been seen. |
| test/pipeline/test_sprint1_hardening.py | TestSprint1Hardening::test_seen_ids_subtraction_with_list_input | **MERGE** | Subsumed by test_seen_ids_set_subtraction_excludes_specified_anime; merge list coercion check. |

### 4.15 test/pipeline/test_sprint2_async_concurrency.py

*Total Items:* 13 | *KEEP:* 8 | *MERGE:* 2 | *DELETE:* 3

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/test_sprint2_async_concurrency.py | TestAC21GpuIODecoupling::test_ac2_1_gpu_compute_vs_io_time | **KEEP** | Performance verification ensuring GPU billing duration remains decoupled from network I/O. |
| test/pipeline/test_sprint2_async_concurrency.py | TestAsyncOpenAIQueryGenerator::test_generate_async_non_blocking_execution | **MERGE** | Subsumed by test_isolated_smoke.py::test_generate_async_success. |
| test/pipeline/test_sprint2_async_concurrency.py | TestAsyncOpenAIQueryGenerator::test_generate_async_fallback_on_openai_error | **MERGE** | Subsumed by test_isolated_smoke.py::test_generate_async_fallback_on_exception. |
| test/pipeline/test_sprint2_async_concurrency.py | TestAsyncRagPipeline::test_async_rag_pipeline_execution_and_timings | **DELETE** | Exact duplicate of test_isolated_smoke.py::test_async_rag_pipeline_execution_and_timings. |
| test/pipeline/test_sprint2_async_concurrency.py | TestEventLoopLagAndConcurrency::test_ac2_2_event_loop_lag_remains_under_15ms | **KEEP (FLAGGED)** | Validates event loop latency under 15ms; flagged for sensitivity to tracer overhead in coverage runs. |
| test/pipeline/test_sprint2_async_concurrency.py | TestEventLoopLagAndConcurrency::test_ac2_2_blocking_baseline_fails_lag_monitor | **DELETE** | Negative harness verification testing lag monitor behaviour rather than production code. |
| test/pipeline/test_sprint2_async_concurrency.py | TestEventLoopLagAndConcurrency::test_ac2_3_twenty_concurrent_requests_stability | **KEEP** | Concurrency stress test evaluating 20 simultaneous requests. |
| test/pipeline/test_sprint2_async_concurrency.py | TestBackwardCompatibility::test_sync_rag_pipeline_signature_and_execution | **DELETE** | Duplicate of test_isolated_smoke.py::test_sync_rag_pipeline_execution_and_timings. |
| test/pipeline/test_sprint2_async_concurrency.py | TestBackwardCompatibility::test_sync_rag_pipeline_preserves_evaluation_scripts_interface | **KEEP (FLAGGED)** | Verifies legacy module export signatures for evaluation scripts. |
| test/pipeline/test_sprint2_async_concurrency.py | TestFastAPIRecommendEndpoint::test_recommend_endpoint_concurrent_async_client | **KEEP** | Integration test sending concurrent requests to POST /recommend via httpx.AsyncClient. |
| test/pipeline/test_sprint2_async_concurrency.py | TestEdgeCasesAndFailureModes::test_openai_api_timeout_graceful_recovery | **KEEP** | Simulates hanging OpenAI API call to verify bounded timeout handling. |
| test/pipeline/test_sprint2_async_concurrency.py | TestEdgeCasesAndFailureModes::test_db_pool_contention_and_queue_handling | **KEEP** | Simulates connection pool contention under 20 concurrent requests. |
| test/pipeline/test_sprint2_async_concurrency.py | TestEdgeCasesAndFailureModes::test_modal_rpc_serialization_safety | **KEEP** | Verifies candidate payload serialisation between Gateway and ModelWorker actors. |

### 4.16 test/pipeline/test_sprint3_guardrails_sse.py

*Total Items:* 7 | *KEEP:* 4 | *MERGE:* 0 | *DELETE:* 3

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/test_sprint3_guardrails_sse.py | TestDualModeDispatchAndSSEStreaming::test_ac3_1_ttft_metadata_event_under_one_point_five_seconds | **KEEP** | Performance benchmark ensuring metadata event TTFT is under 1.5 seconds. |
| test/pipeline/test_sprint3_guardrails_sse.py | TestDualModeDispatchAndSSEStreaming::test_ac3_2_non_anime_prompt_rejected_in_sse_under_15ms | **KEEP** | Performance benchmark ensuring prompt rejection SSE event emits under 15ms. |
| test/pipeline/test_sprint3_guardrails_sse.py | TestDualModeDispatchAndSSEStreaming::test_ac3_3_openai_500_circuit_breaker_sse_delivery | **KEEP** | Circuit breaker resilience test ensuring candidate cards are preserved when OpenAI fails. |
| test/pipeline/test_sprint3_guardrails_sse.py | TestDualModeDispatchAndSSEStreaming::test_recommend_endpoint_backward_compatibility | **DELETE** | Subsumed by test_isolated_smoke.py::test_post_recommend_returns_200_valid_schema. |
| test/pipeline/test_sprint3_guardrails_sse.py | TestDualModeDispatchAndSSEStreaming::test_chat_endpoint_rejects_missing_or_invalid_api_key | **DELETE** | Duplicate of authentication tests in test_sprint9_chat_tier.py and test_api_keys.py. |
| test/pipeline/test_sprint3_guardrails_sse.py | TestDualModeDispatchAndSSEStreaming::test_chat_endpoint_enforces_rate_limiting | **DELETE** | Duplicate of rate limiting tests in test_sprint4_state_and_web_chat.py and test_sprint9_chat_tier.py. |
| test/pipeline/test_sprint3_guardrails_sse.py | TestLowConfidenceStreaming::test_low_confidence_retrieval_emits_warning_event | **KEEP** | Verifies emission of SSE warning event when reranker score falls below -6.5. |

### 4.17 test/pipeline/test_sprint4_state_and_web_chat.py

*Total Items:* 19 | *KEEP:* 12 | *MERGE:* 5 | *DELETE:* 2

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/test_sprint4_state_and_web_chat.py | TestDistributedSlidingWindowRateLimiting::test_ac4_3_multi_container_distributed_rate_limiting | **KEEP** | Acceptance test verifying sliding-window rate limiting across simulated container instances. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestDistributedSlidingWindowRateLimiting::test_ac4_3_http_429_endpoint_response_and_headers | **KEEP** | Verifies RFC 6585 headers (Retry-After, X-RateLimit-*) on HTTP 429 response. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestRateLimiterResilienceAndFallback::test_redis_timeout_falls_back_to_in_memory_window | **KEEP** | Resilience test verifying fallback to in-memory tracking on Redis timeout. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestRateLimiterResilienceAndFallback::test_redis_network_error_falls_back_to_in_memory_window | **MERGE** | Subsumed by test_redis_timeout_falls_back_to_in_memory_window; consolidate Redis exception fallbacks. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestRateLimiterBackwardCompatibility::test_sync_tuple_unpacking | **MERGE** | Consolidate with test_async_await_dual_mode_result into single dual-mode result verification. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestRateLimiterBackwardCompatibility::test_async_await_dual_mode_result | **KEEP** | Verifies dual-mode compatibility allowing both sync unpacking and async await. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestStateManagerFallbackAndUnsetCredentials::test_init_without_credentials_defaults_to_in_memory | **KEEP** | Verifies StateManager initializes in-memory storage when credentials are unset. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestStateManagerFallbackAndUnsetCredentials::test_rolling_five_turns_eviction | **KEEP** | Verifies rolling 5-turn session memory eviction policy. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestStateManagerFallbackAndUnsetCredentials::test_in_memory_session_ttl_expiration | **KEEP** | Verifies TTL expiration and purging of in-memory chat sessions. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestStateManagerTimeoutAndResilience::test_redis_call_timeout_triggers_fallback_within_150ms | **KEEP** | Verifies Redis operation timeout triggers fallback within 150ms ceiling. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestStateManagerTimeoutAndResilience::test_redis_network_exception_falls_back_cleanly | **MERGE** | Subsumed by test_redis_call_timeout_triggers_fallback_within_150ms. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestExclusionFilteringIntegration::test_seen_ids_deduplication_in_ranker | **DELETE** | Duplicate of test_sprint1_hardening.py::test_seen_ids_set_subtraction_excludes_specified_anime. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestHybridLLMCache::test_sqlite_fallback_sync_operations | **KEEP** | Verifies synchronous SQLite fallback operations in hybrid cache. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestHybridLLMCache::test_sqlite_fallback_async_operations | **MERGE** | Consolidate with test_sqlite_fallback_sync_operations into single async/sync cache test. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestConversationalSessionLifecycle::test_chat_auto_generates_session_id_when_not_provided | **KEEP** | Verifies automated generation of session UUID when omitted from chat request. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestAC41MultiTurnPersistenceAcrossContainers::test_ac4_1_session_persistence_across_decoupled_containers | **KEEP** | Verifies conversation persistence across independent container processes. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestAC42WatchedTitleExclusionZeroRecurrence::test_ac4_2_watched_title_exclusion_zero_recurrence | **MERGE** | Subsumed by test_isolated_smoke.py::test_seen_ids_exclusion_zero_recurrence_ac4_2. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestAC44WebConversationalIntegrationSSEStreaming::test_ac4_4_web_conversational_integration_sse_streaming | **KEEP** | End-to-end integration test verifying multi-turn SSE conversation turn flow. |
| test/pipeline/test_sprint4_state_and_web_chat.py | TestClientDisconnectionHandling::test_client_disconnect_aborts_stream_cleanly | **DELETE** | Duplicate of test_streaming_synthesis.py::test_client_disconnection_stops_streaming. |

### 4.18 test/pipeline/test_sprint7_llm_keys.py

*Total Items:* 12 | *KEEP:* 11 | *MERGE:* 1 | *DELETE:* 0

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/test_sprint7_llm_keys.py | TestLayerKeyResolution::test_dedicated_layer_keys | **KEEP** | Verifies resolution of dedicated API keys for NLI, retrieval, and presentation layers. |
| test/pipeline/test_sprint7_llm_keys.py | TestLayerKeyResolution::test_fallback_to_shared_key | **KEEP** | Verifies fallback to shared OPENAI_API_KEY when layer-specific key is omitted. |
| test/pipeline/test_sprint7_llm_keys.py | TestLayerKeyResolution::test_override_key_precedence | **KEEP** | Verifies request-level key override takes precedence over environment variables. |
| test/pipeline/test_sprint7_llm_keys.py | TestLayerKeyResolution::test_missing_all_keys_returns_none | **KEEP** | Verifies graceful return of None when all API keys are absent. |
| test/pipeline/test_sprint7_llm_keys.py | TestQueryGeneratorKeyIsolation::test_initialization_with_retrieval_key | **KEEP** | Verifies QueryGenerator binds specifically to retrieval layer API key. |
| test/pipeline/test_sprint7_llm_keys.py | TestQueryGeneratorKeyIsolation::test_async_generation_logs_tokens | **KEEP** | Verifies asynchronous query generation reports token usage to telemetry. |
| test/pipeline/test_sprint7_llm_keys.py | TestSynthesizerKeyIsolation::test_initialization_with_presentation_key | **KEEP** | Verifies Synthesizer binds specifically to presentation layer API key. |
| test/pipeline/test_sprint7_llm_keys.py | TestSynthesizerKeyIsolation::test_stream_pitch_captures_usage | **KEEP** | Verifies streaming pitch synthesizer captures completion token usage. |
| test/pipeline/test_sprint7_llm_keys.py | TestSynthesizerKeyIsolation::test_fallback_pitch_logs_fallback_status | **KEEP** | Verifies deterministic fallback logs fallback status flag. |
| test/pipeline/test_sprint7_llm_keys.py | TestTelemetryLoggerSafety::test_log_llm_usage_event_safety | **KEEP** | Verifies thread-safe background emission of LLM token telemetry. |
| test/pipeline/test_sprint7_llm_keys.py | TestTelemetryLoggerSafety::test_log_llm_usage_event_never_crashes_on_error | **KEEP** | Verifies logger error isolation preventing caller disruption. |
| test/pipeline/test_sprint7_llm_keys.py | TestKeyRedactionMiddleware::test_openai_key_regex_redaction | **MERGE** | Subsumed by central secret redaction test suite in test_sprint11_smoke.py. |

### 4.19 test/pipeline/test_sprint8_nli.py

*Total Items:* 18 | *KEEP:* 15 | *MERGE:* 3 | *DELETE:* 0

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/test_sprint8_nli.py | TestHeuristicSkipRule::test_turn_1_bypass_empty_or_none_history | **KEEP** | Verifies Turn 1 queries always bypass NLI without executing LLM calls. |
| test/pipeline/test_sprint8_nli.py | TestHeuristicSkipRule::test_turn_1_zero_llm_calls | **MERGE** | Subsumed by test_turn_1_bypass_empty_or_none_history. |
| test/pipeline/test_sprint8_nli.py | TestHeuristicSkipRule::test_turn_2_conversational_cues_trigger_nli | **KEEP** | Verifies Turn 2 conversational cues trigger NLI evaluation. |
| test/pipeline/test_sprint8_nli.py | TestHeuristicSkipRule::test_turn_2_long_standalone_query_bypasses | **KEEP** | Verifies Turn 2 detailed standalone query bypasses NLI evaluation. |
| test/pipeline/test_sprint8_nli.py | TestHeuristicSkipRule::test_turn_2_short_ambiguous_query_triggers_nli | **KEEP** | Verifies Turn 2 short ambiguous follow-up triggers NLI evaluation. |
| test/pipeline/test_sprint8_nli.py | TestNLIParser::test_schema_defaults_and_validation | **KEEP** | Unit verification of Pydantic schema validation for NLI structured output. |
| test/pipeline/test_sprint8_nli.py | TestNLIParser::test_parse_async_success | **KEEP** | Unit verification of successful asynchronous NLI intent parsing. |
| test/pipeline/test_sprint8_nli.py | TestNLIParser::test_parse_async_timeout_fallback | **KEEP** | Verifies 3.0s timeout fallback returning unmodified user query. |
| test/pipeline/test_sprint8_nli.py | TestNLIParser::test_parse_async_exception_fallback | **MERGE** | Subsumed by test_parse_async_timeout_fallback; consolidate NLI exception fallback cases. |
| test/pipeline/test_sprint8_nli.py | TestNLIParser::test_sync_parse_success_and_fallback | **KEEP** | Verifies synchronous parse interface and exception handling. |
| test/pipeline/test_sprint8_nli.py | TestNegativeConstraintFiltering::test_filter_by_avoid_genres_case_insensitive | **KEEP** | Verifies candidate filtering by avoid_genres with case insensitivity. |
| test/pipeline/test_sprint8_nli.py | TestNegativeConstraintFiltering::test_filter_by_multiple_avoid_genres | **MERGE** | Subsumed by test_filter_by_avoid_genres_case_insensitive. |
| test/pipeline/test_sprint8_nli.py | TestNegativeConstraintFiltering::test_filter_by_avoid_tropes | **KEEP** | Verifies candidate filtering by avoid_tropes. |
| test/pipeline/test_sprint8_nli.py | TestNegativeConstraintFiltering::test_filter_empty_constraints_returns_all | **KEEP** | Boundary test ensuring empty negative constraints return all candidates. |
| test/pipeline/test_sprint8_nli.py | TestNegativeConstraintFiltering::test_ranker_execute_applies_negative_filtering | **KEEP** | Verifies integration of negative constraint filtering in Ranker execution. |
| test/pipeline/test_sprint8_nli.py | TestOrchestratorSprint8Integration::test_turn_1_orchestrator_bypasses_nli | **KEEP** | Orchestrator integration test verifying Turn 1 bypasses NLI and reports zero latency. |
| test/pipeline/test_sprint8_nli.py | TestOrchestratorSprint8Integration::test_turn_2_orchestrator_runs_nli_and_filters_negative_genres | **KEEP** | Orchestrator integration test verifying Turn 2 NLI invocation and post-filtering. |
| test/pipeline/test_sprint8_nli.py | TestOrchestratorSprint8Integration::test_turn_2_orchestrator_nli_failure_gracefully_falls_back | **KEEP** | Orchestrator integration test verifying graceful continuation on NLI failure. |

### 4.20 test/pipeline/test_sprint9_chat_tier.py

*Total Items:* 16 | *KEEP:* 11 | *MERGE:* 5 | *DELETE:* 0

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/test_sprint9_chat_tier.py | TestAnonymousSlidingWindowRateLimit::test_anonymous_visitor_allows_5_queries_within_15_minutes | **KEEP** | Verifies anonymous tier quota allowance of 5 requests per 15 minutes. |
| test/pipeline/test_sprint9_chat_tier.py | TestAnonymousSlidingWindowRateLimit::test_anonymous_visitor_blocks_6th_query_with_429_and_retry_after | **KEEP** | Verifies anonymous tier 6th request triggers HTTP 429 with Retry-After header. |
| test/pipeline/test_sprint9_chat_tier.py | TestAnonymousSlidingWindowRateLimit::test_anonymous_rate_limit_is_isolated_per_client_ip | **KEEP** | Verifies rate limit isolation between separate client IP addresses. |
| test/pipeline/test_sprint9_chat_tier.py | TestAuthenticatedUserTierRateLimit::test_authenticated_user_allows_20_queries_within_1_hour | **KEEP** | Verifies authenticated tier quota allowance of 20 requests per hour. |
| test/pipeline/test_sprint9_chat_tier.py | TestAuthenticatedUserTierRateLimit::test_authenticated_user_blocks_21st_query_with_429 | **KEEP** | Verifies authenticated tier 21st request triggers HTTP 429. |
| test/pipeline/test_sprint9_chat_tier.py | TestAuthenticatedUserTierRateLimit::test_authenticated_rate_limit_is_isolated_per_user_id | **KEEP** | Verifies rate limit isolation between separate authenticated user IDs. |
| test/pipeline/test_sprint9_chat_tier.py | TestAuthenticatedUserTierRateLimit::test_invalid_or_expired_supabase_token_returns_401 | **KEEP** | Security test enforcing 401 on invalid or expired Supabase JWT tokens. |
| test/pipeline/test_sprint9_chat_tier.py | TestDeveloperApiKeyBackwardCompatibility::test_developer_key_via_access_token_header | **MERGE** | Subsumed by test_api_keys.py::test_recommend_auth_success_legacy_header. |
| test/pipeline/test_sprint9_chat_tier.py | TestDeveloperApiKeyBackwardCompatibility::test_developer_key_via_authorization_bearer | **MERGE** | Subsumed by test_api_keys.py::test_recommend_auth_success_bearer. |
| test/pipeline/test_sprint9_chat_tier.py | TestDeveloperApiKeyBackwardCompatibility::test_invalid_developer_key_returns_401 | **MERGE** | Subsumed by test_api_keys.py::test_recommend_missing_key_401. |
| test/pipeline/test_sprint9_chat_tier.py | TestDeveloperApiKeyBackwardCompatibility::test_developer_key_enforces_rate_limiting | **MERGE** | Subsumed by test_api_keys.py::test_independent_key_rate_limits. |
| test/pipeline/test_sprint9_chat_tier.py | TestDislikedGenresFiltering::test_disliked_genres_filters_matching_candidate_cards | **KEEP** | Verifies exclusion of anime matching request disliked_genres from SSE metadata cards. |
| test/pipeline/test_sprint9_chat_tier.py | TestDislikedGenresFiltering::test_disliked_genres_case_insensitive_matching | **MERGE** | Subsumed by test_disliked_genres_filters_matching_candidate_cards. |
| test/pipeline/test_sprint9_chat_tier.py | TestDislikedGenresFiltering::test_disliked_genres_merged_with_nli_avoid_genres | **KEEP** | Verifies merging of request disliked_genres and NLI avoid_genres. |
| test/pipeline/test_sprint9_chat_tier.py | TestRateLimitEnvelopeAndCountdown::test_uniform_429_error_envelope_schema | **KEEP** | Verifies schema conformity of the uniform API error envelope on 429 responses. |
| test/pipeline/test_sprint9_chat_tier.py | TestRateLimitEnvelopeAndCountdown::test_retry_after_countdown_reflects_sliding_window_progress | **KEEP** | Verifies countdown decrement of Retry-After header as sliding window progresses. |

### 4.21 test/pipeline/test_streaming_synthesis.py

*Total Items:* 9 | *KEEP:* 6 | *MERGE:* 3 | *DELETE:* 0

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/pipeline/test_streaming_synthesis.py | TestRecommendationSynthesizerStreaming::test_normal_streaming_yields_expected_tokens | **KEEP** | Verifies streaming synthesis yields expected token sequence. |
| test/pipeline/test_streaming_synthesis.py | TestRecommendationSynthesizerStreaming::test_streaming_scrubs_spoilers_across_tokens | **KEEP** | Verifies spoiler scrubbing across token boundaries in live stream. |
| test/pipeline/test_streaming_synthesis.py | TestRecommendationSynthesizerStreaming::test_client_disconnection_stops_streaming | **KEEP** | Verifies immediate cessation of token generation on client disconnection. |
| test/pipeline/test_streaming_synthesis.py | TestCircuitBreakerAndFallbacks::test_ac3_3_openai_500_circuit_breaker_fallback | **MERGE** | Subsumed by test_sprint3_guardrails_sse.py::test_ac3_3_openai_500_circuit_breaker_sse_delivery. |
| test/pipeline/test_streaming_synthesis.py | TestCircuitBreakerAndFallbacks::test_ac3_3_openai_timeout_circuit_breaker_fallback | **MERGE** | Subsumed by test_ac3_3_openai_500_circuit_breaker_fallback; consolidate circuit breaker fallbacks. |
| test/pipeline/test_streaming_synthesis.py | TestCircuitBreakerAndFallbacks::test_unconfigured_api_key_falls_back_gracefully | **KEEP** | Verifies graceful delivery of fallback pitch when OpenAI API key is missing. |
| test/pipeline/test_streaming_synthesis.py | TestContextGroundingConstraints::test_system_prompt_strictly_enforces_grounding | **KEEP** | Verifies synthesizer system prompt enforces grounding constraints. |
| test/pipeline/test_streaming_synthesis.py | TestDualStreamSSEProtocol::test_dual_stream_sse_event_sequencing | **KEEP** | Verifies protocol sequencing of metadata, token, and done SSE events. |
| test/pipeline/test_streaming_synthesis.py | TestDualStreamSSEProtocol::test_dual_stream_sse_circuit_breaker_preserves_cards | **MERGE** | Subsumed by test_dual_stream_sse_event_sequencing. |

### 4.22 test/test_api_keys.py

*Total Items:* 27 | *KEEP:* 25 | *MERGE:* 1 | *DELETE:* 1

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/test_api_keys.py | TestKeyLifecycle::test_key_generation_and_entropy | **KEEP** | Verifies cryptographically secure key generation and prefix format. |
| test/test_api_keys.py | TestKeyLifecycle::test_hmac_hashing_and_pepper_secrecy | **KEEP** | Verifies HMAC-SHA256 hashing and pepper isolation. |
| test/test_api_keys.py | TestKeyLifecycle::test_tampered_pepper_fails_validation | **KEEP** | Verifies authentication failure when pepper value is modified. |
| test/test_api_keys.py | TestEndpointAuth::test_recommend_auth_success_bearer | **KEEP** | Verifies Authorization: Bearer authentication on /recommend. |
| test/test_api_keys.py | TestEndpointAuth::test_recommend_auth_success_legacy_header | **KEEP** | Verifies backward-compatible access_token header on /recommend. |
| test/test_api_keys.py | TestEndpointAuth::test_recommend_missing_key_401 | **KEEP** | Verifies 401 response on missing API key. |
| test/test_api_keys.py | TestEndpointAuth::test_recommend_revoked_key_401 | **KEEP** | Verifies 401 response on soft-revoked API key. |
| test/test_api_keys.py | TestEndpointAuth::test_recommend_expired_key_401 | **KEEP** | Verifies 401 response on expired API key. |
| test/test_api_keys.py | TestEndpointAuth::test_admin_recommend_role_gate_matrix | **MERGE** | Subsumed by comprehensive role gate matrix in test_sprint3_telemetry.py. |
| test/test_api_keys.py | TestEndpointAuth::test_env_breakglass_admin_key | **KEEP** | Verifies breakglass ADMIN_API_KEY environment variable authentication. |
| test/test_api_keys.py | TestCacheAndRevocation::test_positive_cache_hit_bypasses_db | **KEEP** | Verifies memory cache hit bypasses database lookup for active keys. |
| test/test_api_keys.py | TestCacheAndRevocation::test_redis_tombstone_invalidates_cache_immediately | **KEEP** | Verifies immediate invalidation of local memory cache upon Redis tombstone broadcast. |
| test/test_api_keys.py | TestDevKeysRouterSecurity::test_missing_jwt_returns_401 | **KEEP** | Security test enforcing 401 when POST /dev/keys lacks JWT. |
| test/test_api_keys.py | TestDevKeysRouterSecurity::test_expired_jwt_returns_401 | **KEEP** | Security test enforcing 401 when POST /dev/keys provides expired JWT. |
| test/test_api_keys.py | TestDevKeysRouterSecurity::test_stale_jwt_rejected_on_key_creation | **DELETE** | Exact duplicate of test_sprint6_security_rls.py::test_07_dev_keys_stale_session_rejected. |
| test/test_api_keys.py | TestDevKeysRouterSecurity::test_alg_none_forgery_rejected | **KEEP** | Security test rejecting JWT tokens with alg=none forgery attack. |
| test/test_api_keys.py | TestDevKeysRouterSecurity::test_hs256_public_key_confusion_rejected | **KEEP** | Security test rejecting RSA public key confusion attacks (HMAC-SHA256 using RSA public key). |
| test/test_api_keys.py | TestDevKeysRouterSecurity::test_wrong_aud_claim_rejected | **KEEP** | Security test rejecting JWT tokens with mismatched aud claim. |
| test/test_api_keys.py | TestDevKeysRouterSecurity::test_mass_assignment_prevented | **KEEP** | Security test rejecting mass-assignment attacks attempting to inject role or scopes. |
| test/test_api_keys.py | TestDevKeysRouterSecurity::test_max_active_keys_limit_returns_409 | **KEEP** | Acceptance test verifying 409 Conflict when attempting to create a 6th active key. |
| test/test_api_keys.py | TestDevKeysRouterSecurity::test_foreign_key_delete_returns_404 | **KEEP** | Security test verifying soft-deleting foreign developer key returns 404 without leaking existence. |
| test/test_api_keys.py | TestDevKeysRouterSecurity::test_dev_keys_fail_closed_on_redis_outage | **KEEP** | Resilience security test ensuring dev keys fail closed during Redis outage. |
| test/test_api_keys.py | TestKeySecrecy::test_raw_key_shown_once_and_never_in_list | **KEEP** | Security test verifying raw key secret is returned only once at creation and never in list queries. |
| test/test_api_keys.py | TestKeySecrecy::test_raw_secret_never_in_db_records | **KEEP** | Security test verifying raw key plaintext is never persisted in database tables. |
| test/test_api_keys.py | TestRateLimiting::test_independent_key_rate_limits | **KEEP** | Verifies rate limits are tracked independently per API key. |
| test/test_api_keys.py | TestRateLimiting::test_pre_auth_ip_failure_throttle | **KEEP** | Security test throttling repeated unauthenticated attempts from offending IP. |
| test/test_api_keys.py | TestBreakGlassCLI::test_cli_create_admin_and_list | **KEEP** | Operational test for administrative CLI key provisioning command. |

### 4.23 test/test_sprint10_presentation.py

*Total Items:* 20 | *KEEP:* 0 | *MERGE:* 3 | *DELETE:* 17

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/test_sprint10_presentation.py | TestSprint10PresentationFiles::test_sprint10_files_exist | **DELETE** | Checks os.path.isfile without runtime assertions. |
| test/test_sprint10_presentation.py | TestConciergePitchCitationContract::test_props_contract | **DELETE** | Static string search on TypeScript interface; replace with native Vitest component test. |
| test/test_sprint10_presentation.py | TestConciergePitchCitationContract::test_structured_citation_pattern | **DELETE** | Static string search on TSX component. |
| test/test_sprint10_presentation.py | TestConciergePitchCitationContract::test_citation_chip_candidate_lookup_and_fallback | **DELETE** | Static string search on TSX component. |
| test/test_sprint10_presentation.py | TestConciergePitchCitationContract::test_citation_chip_styling_and_interactivity | **DELETE** | Static string search on TSX component. |
| test/test_sprint10_presentation.py | TestConciergePitchCitationContract::test_citation_regex_parsing_logic | **MERGE** | Subsumed by test_sprint10_citations.py; consolidate Python regex tests. |
| test/test_sprint10_presentation.py | TestConciergePitchSpoilerContract::test_spoiler_patterns_handled | **DELETE** | Static string search on TSX component. |
| test/test_sprint10_presentation.py | TestConciergePitchSpoilerContract::test_spoiler_component_toggle_state | **DELETE** | Static string search on TSX component. |
| test/test_sprint10_presentation.py | TestConciergePitchSpoilerContract::test_spoiler_unrevealed_state_badge | **DELETE** | Static string search on TSX component. |
| test/test_sprint10_presentation.py | TestConciergePitchSpoilerContract::test_spoiler_revealed_state_transition | **DELETE** | Static string search on TSX component. |
| test/test_sprint10_presentation.py | TestConciergePitchSpoilerContract::test_spoiler_regex_parsing_logic | **MERGE** | Subsumed by test_guardrails.py; consolidate spoiler regex tests. |
| test/test_sprint10_presentation.py | TestAnimeCardHighlightContract::test_dom_id_anchor | **DELETE** | Static string search on TSX component. |
| test/test_sprint10_presentation.py | TestAnimeCardHighlightContract::test_is_highlighted_prop | **DELETE** | Static string search on TSX component. |
| test/test_sprint10_presentation.py | TestAnimeCardHighlightContract::test_highlight_ring_and_glow_styling | **DELETE** | Static string search on TSX component. |
| test/test_sprint10_presentation.py | TestChatPageLinkingContract::test_highlighted_state_management | **DELETE** | Static string search on TSX page component. |
| test/test_sprint10_presentation.py | TestChatPageLinkingContract::test_handle_select_anime_smooth_scroll | **DELETE** | Static string search on TSX page component. |
| test/test_sprint10_presentation.py | TestChatPageLinkingContract::test_auto_clear_highlight_timeout | **DELETE** | Static string search on TSX page component. |
| test/test_sprint10_presentation.py | TestChatPageLinkingContract::test_concierge_pitch_props_passed | **DELETE** | Static string search on TSX page component. |
| test/test_sprint10_presentation.py | TestChatPageLinkingContract::test_anime_card_highlight_prop_passed | **DELETE** | Static string search on TSX page component. |
| test/test_sprint10_presentation.py | TestSecretScannerSprint10::test_no_leaked_secrets_in_sprint10 | **MERGE** | Subsumed by central frontend secret audit test in test_sprint6_security_rls.py. |

### 4.24 test/test_sprint1_migration.py

*Total Items:* 4 | *KEEP:* 4 | *MERGE:* 0 | *DELETE:* 0

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/test_sprint1_migration.py | TestSprint1Migration::test_01_migration_idempotency | **KEEP** | Verifies database migration 001 applies idempotently on repeated execution. |
| test/test_sprint1_migration.py | TestSprint1Migration::test_02_catalog_verification | **KEEP** | Verifies catalogue schemas, tables, full-text indexes, and triggers exist in PostgreSQL. |
| test/test_sprint1_migration.py | TestSprint1Migration::test_03_enforce_max_active_keys_trigger | **KEEP** | Verifies database trigger enforcing the 5-key ceiling per developer. |
| test/test_sprint1_migration.py | TestSprint1Migration::test_04_storage_bucket_verifier_utility | **KEEP (FLAGGED)** | Verifies Supabase storage bucket utility; flagged for remote storage dependence. |

### 4.25 test/test_sprint3_telemetry.py

*Total Items:* 16 | *KEEP:* 14 | *MERGE:* 1 | *DELETE:* 1

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/test_sprint3_telemetry.py | TestScoreStrippingAndPublicContract::test_strip_scores_pure_and_non_mutating | **KEEP** | Verifies strip_scores utility is pure and non-mutating. |
| test/test_sprint3_telemetry.py | TestScoreStrippingAndPublicContract::test_public_recommend_has_zero_timing_or_score_fields | **KEEP** | Verifies public /recommend endpoint returns zero internal timing or score fields. |
| test/test_sprint3_telemetry.py | TestScoreStrippingAndPublicContract::test_chat_sse_strips_scores_and_top_score_at_serialization_only | **KEEP** | Verifies /chat SSE strips internal scoring metrics at serialisation boundary. |
| test/test_sprint3_telemetry.py | TestAdminRecommendEndpointAndAuthMatrix::test_admin_recommend_401_without_key_or_revoked | **KEEP** | Verifies 401 response on /admin/recommend when unauthenticated or revoked. |
| test/test_sprint3_telemetry.py | TestAdminRecommendEndpointAndAuthMatrix::test_admin_recommend_403_with_user_key | **KEEP** | Verifies 403 Forbidden on /admin/recommend when called with developer-tier key. |
| test/test_sprint3_telemetry.py | TestAdminRecommendEndpointAndAuthMatrix::test_admin_recommend_200_with_admin_key_includes_scores_and_timings | **KEEP** | Verifies /admin/recommend returns complete scores, timings, and extra fields. |
| test/test_sprint3_telemetry.py | TestAdminRecommendEndpointAndAuthMatrix::test_cors_preflight_allows_configured_origins_and_exposes_session_id | **MERGE** | Subsumed by test_sprint6_frontend_and_admin_portal.py::test_cors_preflight_allowed_origin_success. |
| test/test_sprint3_telemetry.py | TestBackgroundTelemetryLoggingAndRollup::test_recommend_and_admin_recommend_log_rows_and_daily_usage | **KEEP** | Verifies background logging writes telemetry rows and updates daily usage rollups. |
| test/test_sprint3_telemetry.py | TestBackgroundTelemetryLoggingAndRollup::test_error_paths_log_status_error_before_reraising | **KEEP** | Verifies error paths record error status in telemetry prior to raising. |
| test/test_sprint3_telemetry.py | TestBackgroundTelemetryLoggingAndRollup::test_chat_endpoint_logs_once_per_turn_after_stream_ends | **KEEP** | Verifies SSE streaming chat logs telemetry once per turn after stream completion. |
| test/test_sprint3_telemetry.py | TestTelemetryDataSanitizationAndPrivacy::test_numpy_scalars_nan_inf_truncation_and_ip_hashing | **KEEP** | Verifies sanitization of numpy scalars, NaN, Inf, and cryptographic IP hashing. |
| test/test_sprint3_telemetry.py | TestTelemetryResilienceAndBoundedRetryQueue::test_pool_exhaustion_or_db_outage_never_fails_request | **KEEP** | Resilience verification ensuring telemetry database outage never fails recommendation request. |
| test/test_sprint3_telemetry.py | TestTelemetryResilienceAndBoundedRetryQueue::test_integrity_error_drops_event_without_retry | **KEEP** | Resilience verification ensuring SQL integrity error drops corrupted event without retry. |
| test/test_sprint3_telemetry.py | TestTelemetryResilienceAndBoundedRetryQueue::test_transient_operational_error_queued_and_retried_at_most_once | **KEEP** | Resilience verification ensuring transient operational error is queued and retried at most once. |
| test/test_sprint3_telemetry.py | TestTelemetryLatencyBenchmark::test_added_request_latency_from_telemetry_under_2ms | **KEEP** | Performance benchmark verifying asynchronous telemetry logging adds less than 2ms request latency. |
| test/test_sprint3_telemetry.py | TestHourlyRunAdminMigration::test_hourly_run_points_to_admin_recommend_and_completes | **DELETE** | Targets hourly_run.py, an external operational script outside automated testing. |

### 4.26 test/test_sprint5_e2e_and_workflows.py

*Total Items:* 16 | *KEEP:* 11 | *MERGE:* 5 | *DELETE:* 0

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/test_sprint5_e2e_and_workflows.py | TestWorkflowYamlValidation::test_archive_telemetry_triggers_and_inputs | **MERGE** | Static YAML syntax check; consolidate into single workflow configuration audit. |
| test/test_sprint5_e2e_and_workflows.py | TestWorkflowYamlValidation::test_archive_telemetry_concurrency_timeout_permissions | **MERGE** | Static YAML syntax check; consolidate into single workflow configuration audit. |
| test/test_sprint5_e2e_and_workflows.py | TestWorkflowYamlValidation::test_archive_telemetry_env_secret_isolation_and_deps | **MERGE** | Static YAML syntax check; consolidate into single workflow configuration audit. |
| test/test_sprint5_e2e_and_workflows.py | TestWorkflowYamlValidation::test_update_data_workflow_contract | **MERGE** | Static YAML syntax check; consolidate into single workflow configuration audit. |
| test/test_sprint5_e2e_and_workflows.py | TestDataPipelineSchemaIsolation::test_database_helper_ast_and_queries_isolated | **KEEP** | Strict architectural AST check enforcing container isolation boundary for data pipeline. |
| test/test_sprint5_e2e_and_workflows.py | TestKeepAliveQuery::test_keepalive_db_config_timeouts | **KEEP** | Verifies keepalive connection configuration enforces bounded timeouts. |
| test/test_sprint5_e2e_and_workflows.py | TestKeepAliveQuery::test_keepalive_execution_success | **KEEP** | Verifies keepalive query execution against PostgreSQL pooler. |
| test/test_sprint5_e2e_and_workflows.py | TestKeepAliveQuery::test_keepalive_execution_failure_handling | **KEEP** | Verifies keepalive retry and error handling on transient DB failure. |
| test/test_sprint5_e2e_and_workflows.py | TestAlertDispatchUnit::test_secret_redaction | **MERGE** | Subsumed by central secret redaction test suite in test_sprint11_smoke.py. |
| test/test_sprint5_e2e_and_workflows.py | TestAlertDispatchUnit::test_discord_payload_structure | **KEEP** | Verifies webhook payload formatting for Discord operational alerts. |
| test/test_sprint5_e2e_and_workflows.py | TestAlertDispatchUnit::test_slack_payload_structure | **KEEP** | Verifies webhook payload formatting for Slack operational alerts. |
| test/test_sprint5_e2e_and_workflows.py | TestAlertDispatchUnit::test_github_issue_fallback_and_dedup | **KEEP** | Verifies fallback to GitHub issue creation with deduplication when webhooks fail. |
| test/test_sprint5_e2e_and_workflows.py | TestSprint5FullE2ESimulation::test_complete_sprint5_e2e_acceptance_flow | **KEEP** | End-to-end integration test simulating archival keyset pagination, upload, and verification. |
| test/test_sprint5_e2e_and_workflows.py | TestSprint5FailureInjection::test_failure_injection_db_fetch_error | **KEEP** | Failure injection test simulating database fetch failure during archival. |
| test/test_sprint5_e2e_and_workflows.py | TestSprint5FailureInjection::test_failure_injection_storage_upload_timeout | **KEEP** | Failure injection test simulating storage upload timeout during archival. |
| test/test_sprint5_e2e_and_workflows.py | TestSprint5FailureInjection::test_failure_injection_corrupt_parquet_verification | **KEEP** | Failure injection test simulating checksum mismatch on corrupted Parquet upload. |

### 4.27 test/test_sprint6_frontend_and_admin_portal.py

*Total Items:* 31 | *KEEP:* 5 | *MERGE:* 9 | *DELETE:* 17

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/test_sprint6_frontend_and_admin_portal.py | TestFrontendStaticAndContract::test_frontend_project_structure | **DELETE** | Checks os.path.exists on frontend files without runtime assertions. |
| test/test_sprint6_frontend_and_admin_portal.py | TestFrontendStaticAndContract::test_frontend_package_json_dependencies | **DELETE** | Static check on npm package.json strings in a Python test suite. |
| test/test_sprint6_frontend_and_admin_portal.py | TestFrontendStaticAndContract::test_frontend_env_contract_and_absence_of_backend_secrets | **MERGE** | Subsumed by central frontend secret audit test in test_sprint6_security_rls.py. |
| test/test_sprint6_frontend_and_admin_portal.py | TestFrontendStaticAndContract::test_static_secret_scanner_frontend_files | **MERGE** | Subsumed by test_sprint6_security_rls.py::test_10_frontend_secret_leak_prevention_audit. |
| test/test_sprint6_frontend_and_admin_portal.py | TestFrontendStaticAndContract::test_client_key_zeroing_and_state_drop_contract | **DELETE** | Static regex string search on React component; replace with native Vitest component test. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDevPortalApiContract::test_dev_keys_create_success_and_single_reveal | **MERGE** | Subsumed by test_sprint6_security_rls.py::test_06_dev_keys_fresh_session_permitted. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDevPortalApiContract::test_dev_keys_create_mass_assignment_rejected | **MERGE** | Subsumed by test_api_keys.py::test_mass_assignment_prevented. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDevPortalApiContract::test_dev_keys_create_max_limit_409_conflict | **MERGE** | Subsumed by test_api_keys.py::test_max_active_keys_limit_returns_409. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDevPortalApiContract::test_dev_keys_list_never_reveals_secret_or_hash | **MERGE** | Subsumed by test_api_keys.py::test_raw_key_shown_once_and_never_in_list. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDevPortalApiContract::test_dev_keys_delete_soft_revoke_idempotent | **KEEP** | Verifies DELETE /dev/keys/{id} executes soft revocation idempotently. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDevPortalApiContract::test_dev_keys_delete_foreign_key_404_isolation | **MERGE** | Subsumed by test_api_keys.py::test_foreign_key_delete_returns_404. |
| test/test_sprint6_frontend_and_admin_portal.py | TestKeyLifecycleAndRevocationLag::test_new_developer_self_service_onboarding_lifecycle | **KEEP** | Integration test verifying complete developer onboarding flow from key creation to invocation. |
| test/test_sprint6_frontend_and_admin_portal.py | TestAdminTelemetryPostgrestContract::test_admin_telemetry_schema_and_query_builder | **DELETE** | Static regex string search on TypeScript hook; replace with native Vitest hook test. |
| test/test_sprint6_frontend_and_admin_portal.py | TestAdminTelemetryPostgrestContract::test_admin_telemetry_pagination_and_hard_limit_guard | **DELETE** | Static regex string search on TypeScript hook; replace with native Vitest hook test. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDatabaseRLSPolicies::test_rls_anon_role_zero_rows | **DELETE** | Trivial mock test testing a local Python helper; subsumed by real PostgreSQL RLS test in test_sprint6_security_rls.py. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDatabaseRLSPolicies::test_rls_normal_authenticated_user_zero_rows | **DELETE** | Trivial mock test; subsumed by real PostgreSQL RLS test in test_sprint6_security_rls.py. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDatabaseRLSPolicies::test_rls_admin_authenticated_user_access_allowed | **DELETE** | Trivial mock test; subsumed by real PostgreSQL RLS test in test_sprint6_security_rls.py. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDatabaseRLSPolicies::test_rls_user_metadata_spoofing_prevented | **DELETE** | Trivial mock test; subsumed by real PostgreSQL RLS test in test_sprint6_security_rls.py. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDatabaseRLSPolicies::test_rls_app_auth_schema_isolated_from_client_roles | **DELETE** | Reads migration file text looking for REVOKE string; subsumed by real DB test test_sprint6_security_rls.py::test_05_rls_app_auth_schema_isolation. |
| test/test_sprint6_frontend_and_admin_portal.py | TestCorsPreflightConfiguration::test_cors_preflight_allowed_origin_success | **KEEP** | Verifies OPTIONS preflight request from allowed origin returns 200 with appropriate CORS headers. |
| test/test_sprint6_frontend_and_admin_portal.py | TestCorsPreflightConfiguration::test_cors_preflight_untrusted_origin_rejected | **KEEP** | Verifies OPTIONS preflight request from untrusted origin is rejected. |
| test/test_sprint6_frontend_and_admin_portal.py | TestCorsPreflightConfiguration::test_cors_allowed_methods_and_headers | **MERGE** | Subsumed by test_cors_preflight_allowed_origin_success. |
| test/test_sprint6_frontend_and_admin_portal.py | TestCorsPreflightConfiguration::test_cors_exposed_headers_present | **MERGE** | Subsumed by test_cors_preflight_allowed_origin_success. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDocumentationAndCodeSamplesContract::test_readme_docs_updated_for_bearer_auth | **DELETE** | Reads markdown documentation text; lacks runtime executable assertions. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDocumentationAndCodeSamplesContract::test_architecture_docs_sprint6_completeness | **DELETE** | Reads markdown documentation text; lacks runtime executable assertions. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDocumentationAndCodeSamplesContract::test_deployment_todo_secrets_updated | **DELETE** | Reads markdown documentation text; lacks runtime executable assertions. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDocumentationAndCodeSamplesContract::test_python_code_samples_syntax_and_env_contract | **KEEP (FLAGGED)** | Extracts Python code sample from TSX documentation component and verifies AST parsing. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDocumentationAndCodeSamplesContract::test_javascript_code_samples_syntax_and_env_contract | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDocumentationAndCodeSamplesContract::test_error_code_table_and_rotation_guide_contract | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDocumentationAndCodeSamplesContract::test_public_docs_and_footer_no_internal_leaks | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint6_frontend_and_admin_portal.py | TestDocumentationAndCodeSamplesContract::test_auth_pages_and_legal_links_contract | **DELETE** | Static regex string search on TSX component. |

### 4.28 test/test_sprint6_security_rls.py

*Total Items:* 10 | *KEEP:* 9 | *MERGE:* 1 | *DELETE:* 0

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/test_sprint6_security_rls.py | TestSprint6SecurityAndRLS::test_01_rls_anonymous_client_denied | **KEEP** | Real PostgreSQL RLS verification ensuring anon client receives 0 rows from telemetry. |
| test/test_sprint6_security_rls.py | TestSprint6SecurityAndRLS::test_02_rls_authenticated_non_admin_client_returns_zero_rows | **KEEP** | Real PostgreSQL RLS verification ensuring authenticated non-admin receives 0 rows. |
| test/test_sprint6_security_rls.py | TestSprint6SecurityAndRLS::test_03_rls_admin_client_successfully_reads_telemetry | **KEEP** | Real PostgreSQL RLS verification ensuring authenticated admin successfully reads telemetry. |
| test/test_sprint6_security_rls.py | TestSprint6SecurityAndRLS::test_04_rls_tampered_user_metadata_spoofing_prevented | **KEEP** | Real PostgreSQL RLS security verification preventing privilege escalation via user_metadata tampering. |
| test/test_sprint6_security_rls.py | TestSprint6SecurityAndRLS::test_05_rls_app_auth_schema_isolation | **KEEP** | Real PostgreSQL schema isolation verification ensuring client roles cannot access app_auth tables. |
| test/test_sprint6_security_rls.py | TestSprint6SecurityAndRLS::test_06_dev_keys_fresh_session_permitted | **KEEP** | Verifies fresh JWT session allows developer API key provisioning. |
| test/test_sprint6_security_rls.py | TestSprint6SecurityAndRLS::test_07_dev_keys_stale_session_rejected | **KEEP** | Verifies stale JWT session (> 15 minutes) is rejected with 401 stale_token. |
| test/test_sprint6_security_rls.py | TestSprint6SecurityAndRLS::test_08_dev_keys_anon_token_rejected | **KEEP** | Verifies token with role != authenticated is rejected on dev keys router. |
| test/test_sprint6_security_rls.py | TestSprint6SecurityAndRLS::test_09_cors_dynamic_origins_verification | **MERGE** | Subsumed by test_sprint6_frontend_and_admin_portal.py::test_cors_preflight_allowed_origin_success. |
| test/test_sprint6_security_rls.py | TestSprint6SecurityAndRLS::test_10_frontend_secret_leak_prevention_audit | **KEEP** | Automated static audit scanning frontend source files for leaked backend secrets. |

### 4.29 test/test_sprint9_frontend_chat.py

*Total Items:* 27 | *KEEP:* 0 | *MERGE:* 1 | *DELETE:* 26

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/test_sprint9_frontend_chat.py | TestSprint9ChatDiscoveryFiles::test_all_sprint9_files_exist | **DELETE** | Checks os.path.isfile without runtime assertions. |
| test/test_sprint9_frontend_chat.py | TestAnimeCardContract::test_title_resolution | **DELETE** | Static regex string search on TSX component; replace with native Vitest component test. |
| test/test_sprint9_frontend_chat.py | TestAnimeCardContract::test_score_badge_and_format_pill | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestAnimeCardContract::test_synopsis_truncate_and_expand | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestAnimeCardContract::test_seen_it_toggle_interaction | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestAnimeCardContract::test_more_like_this_interaction | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestAnimeCardContract::test_clickable_genre_badges_dislike_toggle | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestConciergePitchContract::test_streaming_indicator_and_cursor | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestConciergePitchContract::test_spoiler_redacted_replacement | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestConciergePitchContract::test_markdown_and_line_breaks | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestChatInputContract::test_keyboard_submission | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestChatInputContract::test_action_button_send_and_stop | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestChatInputContract::test_prompt_suggestions | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestChatInputContract::test_adult_content_toggle | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestPreferenceDrawerContract::test_watched_counter_and_clear_action | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestPreferenceDrawerContract::test_disliked_genres_and_remove | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestPreferenceDrawerContract::test_reset_preferences | **DELETE** | Static regex string search on TSX component. |
| test/test_sprint9_frontend_chat.py | TestChatPageContract::test_conversation_state_management | **DELETE** | Static regex string search on TSX page component. |
| test/test_sprint9_frontend_chat.py | TestChatPageContract::test_stream_chat_invocation_parameters | **DELETE** | Static regex string search on TSX page component. |
| test/test_sprint9_frontend_chat.py | TestChatPageContract::test_immediate_metadata_grid_mount | **DELETE** | Static regex string search on TSX page component. |
| test/test_sprint9_frontend_chat.py | TestChatPageContract::test_pitch_streaming | **DELETE** | Static regex string search on TSX page component. |
| test/test_sprint9_frontend_chat.py | TestChatPageContract::test_warning_event_banner | **DELETE** | Static regex string search on TSX page component. |
| test/test_sprint9_frontend_chat.py | TestChatPageContract::test_rate_limit_429_countdown_and_recovery | **DELETE** | Static regex string search on TSX page component. |
| test/test_sprint9_frontend_chat.py | TestChatPageContract::test_abort_controller_support | **DELETE** | Static regex string search on TSX page component. |
| test/test_sprint9_frontend_chat.py | TestNavigationRoutesContract::test_app_mounts_chat_page_at_root | **DELETE** | Static regex string search on TSX router component. |
| test/test_sprint9_frontend_chat.py | TestNavigationRoutesContract::test_navbar_contains_discovery_navlink | **DELETE** | Static regex string search on TSX navbar component. |
| test/test_sprint9_frontend_chat.py | TestSecretScannerSprint9::test_no_leaked_secrets | **MERGE** | Subsumed by central frontend secret audit test in test_sprint6_security_rls.py. |

### 4.30 test/test_telemetry_and_archival.py

*Total Items:* 22 | *KEEP:* 19 | *MERGE:* 0 | *DELETE:* 3

| Test File | Test Name / Method | Classification | Reason |
|---|---|---|---|
| test/test_telemetry_and_archival.py | TestSprint4ScopeAndStaticSecurity::test_requirements_archive_pinned_and_minimal | **DELETE** | Static requirements string check without executable runtime assertions. |
| test/test_telemetry_and_archival.py | TestSprint4ScopeAndStaticSecurity::test_archiver_ast_hardcoded_scope_and_no_pandas | **KEEP (FLAGGED)** | Architectural AST boundary check enforcing container isolation by forbidding pandas. |
| test/test_telemetry_and_archival.py | TestSprint4ScopeAndStaticSecurity::test_archiver_sql_constants_strictly_isolated | **DELETE** | Static check for module SQL string constants. |
| test/test_telemetry_and_archival.py | TestSprint4ScopeAndStaticSecurity::test_session_pooler_db_config_enforces_port_5432 | **DELETE** | Duplicate of test_isolated_smoke.py::test_database_config_default_port_detection_ac1_1. |
| test/test_telemetry_and_archival.py | TestArchiverUnitWithFakeCursor::test_keyset_pagination_and_sub_batch_delete_boundaries | **KEEP** | Unit verification of keyset pagination and sub-batch delete boundary logic. |
| test/test_telemetry_and_archival.py | TestArchiverUnitWithFakeCursor::test_non_contiguous_ids_out_of_order_commits_never_delete_gaps | **KEEP** | Critical safety test ensuring non-contiguous IDs never result in premature gap deletions. |
| test/test_telemetry_and_archival.py | TestArchiverUnitWithFakeCursor::test_jsonb_round_trip_and_explicit_pyarrow_schema | **KEEP** | Contract verification of JSONB round-trip decoding and PyArrow schema conformity. |
| test/test_telemetry_and_archival.py | TestArchiverUnitWithFakeCursor::test_deterministic_keys_separate_user_and_admin_eval_prefixes | **KEEP** | Verifies deterministic S3/Supabase storage keys partition user from admin_eval telemetry. |
| test/test_telemetry_and_archival.py | TestArchiverUnitWithFakeCursor::test_compression_ratio_parquet_under_15_percent_of_raw_json | **KEEP** | Benchmark verification demonstrating Parquet file size remains under 15% of raw JSON. |
| test/test_telemetry_and_archival.py | TestArchiverPostgresIntegrationAndFailureInjection::test_upload_failure_after_tenacity_retries_leaves_db_untouched | **KEEP** | Failure injection test verifying storage upload failure leaves database records untouched. |
| test/test_telemetry_and_archival.py | TestArchiverPostgresIntegrationAndFailureInjection::test_upload_transient_failure_recovers_within_5_attempts | **KEEP** | Resilience verification ensuring tenacity retries recover from transient storage errors. |
| test/test_telemetry_and_archival.py | TestArchiverPostgresIntegrationAndFailureInjection::test_verify_mismatch_leaves_db_untouched[truncate_bytes] | **KEEP** | Security verification ensuring truncated Parquet payload fails verification and aborts DB deletion. |
| test/test_telemetry_and_archival.py | TestArchiverPostgresIntegrationAndFailureInjection::test_verify_mismatch_leaves_db_untouched[bitflip_same_size] | **KEEP** | Security verification ensuring bit-flipped Parquet payload fails verification and aborts DB deletion. |
| test/test_telemetry_and_archival.py | TestArchiverPostgresIntegrationAndFailureInjection::test_verify_mismatch_leaves_db_untouched[fewer_rows] | **KEEP** | Security verification ensuring truncated row count fails verification and aborts DB deletion. |
| test/test_telemetry_and_archival.py | TestArchiverPostgresIntegrationAndFailureInjection::test_crash_after_upload_before_delete_converges_on_rerun_without_overwrite | **KEEP** | Crash recovery test ensuring idempotent rerun after partial completion does not overwrite storage. |
| test/test_telemetry_and_archival.py | TestArchiverPostgresIntegrationAndFailureInjection::test_delete_failure_mid_transaction_rolls_back_and_rerun_converges | **KEEP** | Transaction rollback verification ensuring partial delete failure rolls back cleanly. |
| test/test_telemetry_and_archival.py | TestArchiverPostgresIntegrationAndFailureInjection::test_concurrent_advisory_lock_held_exits_cleanly | **KEEP** | Concurrency safety test ensuring archiver exits cleanly when PostgreSQL advisory lock is held. |
| test/test_telemetry_and_archival.py | TestArchiverPostgresIntegrationAndFailureInjection::test_api_keys_older_than_30_days_survive_and_usage_rollup_preserved | **KEEP** | Data retention verification ensuring active API keys and usage rollups survive 30-day archival. |
| test/test_telemetry_and_archival.py | TestArchiverPostgresIntegrationAndFailureInjection::test_cutoff_boundary_and_out_of_order_newer_id_preservation | **KEEP** | Boundary test ensuring telemetry records newer than cutoff date are strictly preserved. |
| test/test_telemetry_and_archival.py | TestArchiverPostgresIntegrationAndFailureInjection::test_dry_run_writes_nothing_and_deletes_nothing | **KEEP** | Operational safety verification ensuring dry-run mode performs no mutations. |
| test/test_telemetry_and_archival.py | TestArchiverPostgresIntegrationAndFailureInjection::test_privacy_erasure_hot_and_cold_parquet | **KEEP** | GDPR compliance verification validating privacy erasure across both PostgreSQL and cold Parquet files. |
| test/test_telemetry_and_archival.py | TestArchiverPostgresIntegrationAndFailureInjection::test_cli_end_to_end_synthetic_smoke_test_with_manifest | **KEEP** | Operational CLI smoke test executing synthetic archival run and producing manifest. |

---

## 5. Pruning and Action Plan for Sprint 2

1. **Execute Deletions (84 items)**:
   - Remove 63 static string-matching regex assertions on frontend TSX files across `test_sprint9_frontend_chat.py`, `test_sprint10_presentation.py`, `test_sprint6_frontend_and_admin_portal.py`, and `test_sprint11_admin_usage.py`. These will be replaced in subsequent sprints by genuine Vitest component tests.
   - Remove 7 standalone benchmark, experiment, and probe scripts (`hourly_run.py`, `SBERT_TEST.py`, `compare_embeddings.py`, `experiment_k.py`, `evaluate_first_stage.py`, `evaluate_pipeline.py`, `generate_report.py`) from pytest discovery.
   - Remove exact duplicate and framework testing methods in `test_sprint2_async_concurrency.py`, `test_sprint3_guardrails_sse.py`, `test_sprint4_state_and_web_chat.py`, and `test_telemetry_and_archival.py`.

2. **Consolidate Merges (60 items)**:
   - Consolidate duplicated RSA-2048 key generation and JWKS mock doubles across 6 test files into a single shared session-scoped fixture in `conftest.py`.
   - Consolidate secret redaction checks into the central suite in `test_sprint11_smoke.py`.
   - Parameterise duplicate test methods covering boundary conditions (e.g. empty/short query validation, layer budget formatting, and bracket splits).

3. **Protect and Refine Flagged Tests (5 items)**:
   - `test_ac2_2_event_loop_lag_remains_under_15ms`: Provide configurable threshold when running under pure-Python coverage tracers.
   - `test_sync_rag_pipeline_preserves_evaluation_scripts_interface`: Preserve legacy import contract verification.
   - `test_04_storage_bucket_verifier_utility`: Ensure robust mocking when remote Supabase storage is unreachable.
   - `test_python_code_samples_syntax_and_env_contract`: Retain AST syntax validation of documentation code samples.
   - `test_archiver_ast_hardcoded_scope_and_no_pandas`: Enforce container isolation boundary rule.
