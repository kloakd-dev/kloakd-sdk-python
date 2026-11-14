# Changelog

All notable changes to `kloakd-sdk` are documented here.

Format: [Semantic Versioning](https://semver.org/). Types: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.

---

## [Unreleased]

For the crawl-estimate contract of 14 November 2026 (kobe-scraper
feature/2026-11-14-crawl-estimate, not yet merged). `ROUTES.md` lists the
routes.

### Added
- `webgrph.estimate_crawl(url, max_depth=None, max_pages=None)` and
  `webgrph.estimate_crawl_extract(url, max_depth=None, max_pages=None,
  extract=None)` (sync and async): what a crawl or crawl-extract would do
  before it starts, as a `CrawlEstimate` (clamped depth and pages, plan
  limits, site probe, estimated pages, time budget, duration range, GB
  against what remains, warning, explanation). Not metered.
- `webgrph.continue_crawl(crawl_id, max_pages=None, max_depth=None)`: raise
  a partial crawl's limits when continuing it. 422 `continue_cannot_lower`
  for a lower value.
- `webgrph.continue_crawl_extract(job_id, max_pages=None, max_depth=None)`
  and `CrawlExtractContinueResult`.
- `CrawlResult` and `CrawlExtractStatus` gain `time_budget_s`, `elapsed_s`
  and `est_remaining_s` (None until the crawl reports them).

### Changed
- `continue_crawl(crawl_id)` without options sends no body (0.7.0 sent
  `{}`); the API treats both as a plain continue.

---

## [0.7.0] — 2026-11-12

For the API at kobe-scraper 6bd19e9b (main, 12 November 2026); the batch
and unified scrape methods and the route list are of
integration/2026-11-12b (228857dc). **Breaking**:
two methods and some attributes the API never filled are removed, and a
crawl without `max_depth` or `max_pages` now runs to the plan's limits, so
this release is 0.7.0. `ROUTES.md` lists the routes.

### Removed
- `PageNode.status_code` and `PageNode.crawl_parent_url`: the pages listing
  sends neither, so both were always None.
- `ExtractionResult.has_more` and `total` (`kolektr.page`, `extract_html`):
  the extract answer has neither. `total_records` is the count; the API
  returns every record in the one response.
- `NexusAnalyzeResult.error`, `NexusSynthesisResult.error`,
  `NexusVerifyResult.error`: no answer carries it; a failed call raises.
  `ok` stays.
- `nexus.execute` and `NexusExecuteResult` (sync and async): the API removed
  `POST nexus/execute`; the call could only fail.
- `nexus.knowledge` and `NexusKnowledgeResult`: the route now takes
  `{strategy_id, url, outcome}` (the old `{execution_result_id}` body is
  refused) and is not part of the public API reference.

### Added
- Crawl, extract and download in one job (`webgrph`, sync and async):
  `start_crawl_extract`, `crawl_extract`, `get_crawl_extract`,
  `wait_for_crawl_extract`, `get_crawl_extract_results`,
  `iter_crawl_extract_results`, `crawl_extract_all_results`,
  `get_crawl_extract_pages`, `export_crawl_extract` (stream),
  `download_crawl_extract` (file), `cancel_crawl_extract`. Models
  `CrawlExtractJob`, `CrawlExtractStatus`, `CrawlExtractRow`,
  `CrawlExtractResultsPage`, `CrawlExtractPage`, `CrawlExtractPagesResult`,
  `CrawlExtractCancelResult`, `ExportDownload`, `AsyncExportDownload`,
  `SavedExport`. A `limit` outside 1-1000 or a `format` other than `json`,
  `ndjson` or `csv` raises `ValueError` before the request.
- `client.export_batch_job` and `client.download_batch_job` (sync and
  async): a batch job's results as json, ndjson or csv.
- Batch jobs (`client`, sync and async): `create_batch_job(urls,
  extraction_config, crawl_id, entity_type, fields)`, `get_batch_job`,
  `list_batch_jobs`, `get_batch_job_results`, `pause_batch_job`,
  `resume_batch_job`, `cancel_batch_job`. A control the batch's state does
  not allow raises a 409 `ApiError` with `code` `invalid_batch_transition`;
  repeating a control answers the batch as it is; a resume or a create that
  could not be queued raises a 503 `ApiError` with `code` `dispatch_failed`
  and is not retried. Models `BatchJob`, `BatchJobsPage`, `BatchJobItem`,
  `BatchJobResults`.
- Unified scrape (`client`, sync and async): `unified_scrape(url, prompt,
  mode, schema, options, context, constraints, session_artifact_id)`
  (`POST scraping/unified`, a 202 hand-off is followed) and
  `get_unified_scrape(job_id)`. Models `UnifiedScrapeResult`,
  `UnifiedScrapeStatus`, `UnifiedScrapeProgress`, `UnifiedEscalation`.
- `ConcurrencyLimitError.active_crawls` is also filled from the batch
  limit's 409 (`create_batch_job`, `resume_batch_job`), which sends the
  count as `active_batches`.
- `NexusVerifyResult.status`, `risk_score`, `safety_checks`
  (`NexusSafetyCheck`), `verification_result_id`, `duration_ms`.
- Crawls held for quota (sync and async). A crawl whose organization ran
  out of quota is paused (`held_quota`), not failed, and resumes by itself.
  `webgrph.crawl`, `crawl_all` and the new `wait_for_crawl` return it at
  once with `CrawlResult.held` True, `success` False, `error` None and
  `message` the server's text, instead of polling to the timeout.
  `client.crawl` returns `SiteCrawlResult.held` with the new `crawl_id`,
  `crawl_status` and `message`; `crawl_stream`'s `discovery_complete` event
  carries `crawl_id`, `status`, `held` and `message`.
  `CrawlExtractStatus.held` is True while a crawl-extract job's crawl is
  held, and `wait_for_crawl_extract` / `crawl_extract` return the job then.
- `webgrph.wait_for_crawl(crawl_id, poll_timeout, poll_interval, url="")`:
  wait for a crawl you already started (or one that was held or continued).
- What a crawl did: `CrawlResult.is_partial`, `partial_reason`, `resumable`,
  `pages_discovered`, `pages_fetched`, `pages_unfetched`, `error_code`,
  `message`. A crawl that stopped early ends `completed` with `is_partial`
  True.
- `webgrph.continue_crawl(crawl_id)` (`CrawlContinueResult`): fetch the rest
  of a partial crawl on the same id; 409 (`ApiError`) when it cannot be
  continued.
- `CrawlExtractStatus.crawl` (`CrawlExtractCrawl`): the status, counts and
  partial reason of the job's crawl.
- `ExportDownload.crawl`, `AsyncExportDownload.crawl` and
  `SavedExport.crawl` (`ExportCrawl`), read from a crawl-extract export's
  `X-Crawl-*` headers; None for a batch export, which sends none (its
  `job_status` is None too).
- Login sessions for your own account (`fetchyr`, sync and async):
  `start_login_session` (`LoginSession`), `get_session` (`SessionStatus`),
  `resume_session`.
- `PageNode.fetch_status` and `fetch_error`.
- `ExtractionResult.level`, `level_reason` and `login_options`.

### Changed
- `max_depth` and `max_pages` are sent only when given (`webgrph.crawl`,
  `crawl_all`, `crawl_stream`, `client.crawl`, `client.crawl_stream`). They
  were sent as 3 and 100; without them the plan's limits now apply.
- `nexus.reason(timeout_secs=...)` accepts a fraction of a second.
- The route list the contract test checks against was generated again
  from kobe-scraper integration/2026-11-12b (228857dc): 280 routes. The API
  removed its 12 `performance/...` routes; the SDK called none. The test
  also covers the new methods.
- Exports are streamed and read without a read timeout; an error status is
  raised (and retried) as for any GET before the body is handed on.
- `User-Agent: kloakd-sdk-python/0.7.0`.

### Fixed
- `skanyr.get_extraction_text` returns the body as it is. It was parsed as
  JSON first, so a text such as `123` or `{"a": 1}` did not come back as a
  string.

## [0.6.0] — 2026-11-03

For the API deployed on 2 November 2026 (kobe-scraper 0bb0c6b5). Backward
compatible with 0.5.0: without the new arguments every request is the same
as before. `ROUTES.md` lists the calls that changed.

### Added
- `item_selector` on `kolektr.page`, `page_all` and `extract_html` (sync and async), sent as `schema_spec.item_selector`: one record per element it matches, each field read inside that element (first match, every match for `type: "list"`, the named `attribute`, `None` when nothing matches, the item element itself for a field without a selector). Works with the shorthand, a list of fields and a full spec. An empty `item_selector` or one without fields raises `ValueError` (the API answers 422).
- `kloakd.schema_spec(schema, item_selector=None)`, which builds the full spec (for example for `client.crawl(extract_schema=...)`), and the `SchemaSpec` / `SchemaField` TypedDicts.
- `include_grouping` on `webgrph.get_crawl_pages` and `crawl_all_pages` (sync and async), and `limit` on `crawl_all_pages`. Without it only fetched pages are listed, as the API now does by default.
- `PageNode.parent_url`, `is_grouping` and `crawl_parent_url` (the last from stored page dicts only; the pages listing does not send it).
- `ConcurrencyLimitError.active_requests` (409 `concurrent_limit` from the work-slot limit: Free 2, Starter 5, Pro 10, Pro+ 20, Developer 50, Enterprise 100) and a `repr` with all its fields.

### Changed
- `webgrph.get_crawl_pages` raises `ValueError` for a `limit` outside 1-1000 or a `cursor` that is not a non-negative integer, instead of sending a request the API answers with 422.
- In the shorthand, the `css:` prefix is also removed from a dict value's `selector` (`{"title": {"selector": "css:h3 a"}}`).
- `CrawlResult.total_pages` and `max_depth_reached` count fetched pages only (the API's change; documented).
- `User-Agent: kloakd-sdk-python/0.6.0`.

## [0.5.0] — 2026-10-28

Fixes from an audit against kobe-scraper e5f15f7d. Several are breaking,
hence 0.5.0. `ROUTES.md` lists the calls whose request or response changed.

### Changed (breaking)
- `parlyr.chat` / `chat_stream` read the events the API sends (`{type, content, data, actions, timestamp}`, closed by `end`). `ChatEvent` is now `type, content, data, actions, timestamp` (`event` remains as a read-only alias of `type`). `ChatTurn` is now `session_id, response, intent, interpretation, results, errors, warnings, events` and `ok`; `confidence`, `tier`, `entities`, `requires_action` and `clarification_needed` are removed (the stream never carried them). `intent` is `interpretation.get("intent")`, which the API does not send today, so it is usually None. `error` events are collected in `errors`, not raised.
- `nexus.reason(query_type, parameters)`: `parameters` is a list of strings (default `[]`).
- `skanyr.update_site(site_id, policy)`: `policy` is a required string.
- `skanyr.get_site_apis`, `get_site_resources`, `get_findings`, `get_technologies` and `list_resources` return lists.
- `skanyr.export_site` returns the ZIP archive as `bytes`; `skanyr.get_extraction_text` returns `str`.
- `fetchyr.create_multi_site_workflow(dependencies=...)` takes a list of `{dependent_site, dependency_site, dependency_type?}`.
- `webgrph.list_sessions(active_only=True)` always sends `active_only`.
- `FetchEvent` matches the API: `type, stage_id, status, message, progress_pct, metadata, error, sequence, job_id, tier_used, artifact_id` (`tier` and `vendor` are removed).
- A 403 other than `not_entitled` / `tier_access_denied` raises `ForbiddenError`, not `NotEntitledError`. `NotEntitledError` is a subclass of `ForbiddenError`.
- POST, PUT and PATCH are no longer retried on 5xx; network errors are retried only for GET, HEAD and DELETE.
- The playground quota (429 with `retry_after` 0 and no `reset_at`) is no longer retried.
- `crawl()` / `crawl_stream()` report the crawl's own `success` and `error`, and raise `PaymentRequiredError`, `QuotaExceededError`, `BillingUnavailableError`, `NotEntitledError`, `AuthenticationError` and `RateLimitError` instead of marking every page failed.

### Added
- `client.get_handoff(job_id)` and `client.wait_for_handoff(job_id, poll_interval, timeout)` (sync and async), to resume a request after `JobTimeoutError`.
- `ConcurrencyLimitError` (409 `concurrent_limit`: `concurrent_limit`, `active_crawls`, `tier`) and `ForbiddenError`.
- `code` on every error (the API's `detail.error`).
- `NotEntitledError.feature`, `current_tier`, `required_tier` (`tier_access_denied`).
- `RateLimitError.quota_exhausted`, `quota_used`, `quota_limit`, `upgrade_url`.
- `FetchResult` and `ExtractionResult`: `auth_required`, `discovery_id`.
- `CrawlEvent`: `status`, `message`, `error`, `sequence`.
- Paging parameters: `kolektr.list_jobs(page, limit, status_filter)`, `list_scrapers(page, page_size, is_template)`, `list_content(page, page_size, search)`, `fetchyr.list_workflows(page, page_size)`; `endpoint_hash` on the kolektr api-data calls and `max_records` on `extract_all_api_data`.
- Extraction schemas may be a list of fields; `crawl(extract_schema=...)` takes the same forms as `kolektr.page`.
- `kloakd/py.typed` is shipped, so type checkers use the SDK's annotations.
- A `User-Agent: kloakd-sdk-python/0.5.0` header.

### Fixed
- The default `timeout` is 100 s (was 60 s), above the API's 85 s synchronous wait, so a long request receives its 202 hand-off instead of a client timeout. It applies to each attempt.
- 429 `rate_limited` is retried on any method after `Retry-After`, the body's `retry_after`, or until `reset_at`; 503 `billing_unavailable` is retried on any method.
- A non-JSON response (a proxy error page, a text route) no longer raises `JSONDecodeError`; on an error its text is the message.
- A 422's validation messages (`detail[]`) are kept in the message.
- The `css:` shorthand prefix is removed only at the start of a selector.
- Path segments are percent-encoded, including the api-data endpoint URL.
- README and `examples/quickstart.py`: no fetch artifact passed as `session_artifact_id`, no polling after `webgrph.crawl()` (it already waits), no `completed_pages`, and `site_from_crawl` returns `site_id`. The GitHub link points to `kloakd-dev`.

## [0.4.0] — 2026-10-28

The API now hands off more requests as a job, and has deleted the routes
that returned invented results. The removals are breaking, hence 0.4.0.
`ROUTES.md` lists each route.

### Removed (breaking)
- Nexus recommendations, whose 13 `nexus/recommendations/*` routes are deleted: `recommend_analyze`, `list_recommendation_applications`, `get_cache_statistics`, `cleanup_cache`, `invalidate_cache`, `get_hooks_status`, `enable_hook`, `disable_hook`, `create_preference`, `get_preferences`, `update_preference`, `delete_preference`, `get_recommendation_statistics`.
- `kolektr.create_job` (POST `kolektr/jobs` is deleted). `list_jobs` and `get_job` stay.
- Kolektr job progress, progress phases and pipeline, whose routes are deleted: `get_job_progress`, `get_job_progress_events`, `get_job_progress_latest`, `get_job_progress_summary`, `list_progress_phases`, `get_progress_phase`, `get_progress_phase_steps`, `get_progress_summary`, `get_pipeline_events`, `get_pipeline_stream`.
- `webgrph.get_job_trends` and `get_error_summary` (routes deleted).
- The other `webgrph` analytics calls: `get_dashboard_summary`, `get_discovery_patterns`, `get_efficiency_metrics`, `get_site_mapping_trends`, `get_user_behavior_insights`. Their routes belong to the dashboard and are not part of the public API.
- `evadr.list_profiles` (GET `evadr/profiles` is deleted). `list_vendors` stays.

### Added
- Hand-off following on every route that can answer 202: `kolektr.page` / `page_all`, `fetchyr.authenticate`, `detect_forms`, `fill_form`, `detect_mfa`, and `nexus.analyze`, `synthesize`, `execute`, as well as `evadr.fetch`. The SDK polls the `poll_url` the 202 gives and returns the same typed result as a direct answer.
  - A failed job raises `JobFailedError`, and so does a job that is unknown or expired (poll 404).
  - A job still running when the wait runs out raises `JobTimeoutError`.
- `Kloakd(..., poll_interval=3.0, poll_timeout=900.0)` (and on `AsyncKloakd`): the first wait before polling and the overall limit. Each later wait is half as long again, up to 15 s.
- `NexusExecuteResult.execution_result_id`: the id `nexus.knowledge()` takes.

### Changed
- `evadr.fetch` and `evadr.wait_for_job` use the same follower. They wait before the first poll and back off; before, they polled at a fixed interval and polled once straight away.
- A `poll_url` given as a full URL is followed only when it is on the client's base URL, because the poll carries the API key.

## [0.3.0] — 2026-10-27

Every request is now a live API route: `tests/test_contract.py` calls each
public method of the sync and the async client and checks it against the
API's route list. The table of what changed per call is in `ROUTES.md`.

### Changed (breaking)
- `fetchyr.login(...)` is replaced by `fetchyr.authenticate(credential_name, target_url)`; store credentials first with `store_credentials(name, username, password)`.
- `nexus.analyze(url, html, constraints=None)` and `nexus.synthesize(url, html, goal)` take what the API requires; result fields follow the API (`verified`, `program`, `patterns`, …). `nexus.reason(query_type, parameters)`, `nexus.create_preference(user_id, preference_type, value)`.
- `fetchyr.create_workflow(name, steps, description=None, workflow_type=None)`, `execute_workflow(workflow_id, target_url, ...)`, `create_multi_site_workflow(name, sites, ...)`, `create_dedup_session(name, strategy=None)`, `submit_mfa(challenge_id, resolution)` (resolves via the MFA queue, returns `MfaChallenge`).
- `fetchyr.check_duplicates(records)` is replaced by `check_duplicate(url, content_hash=None, session_id=None)` → `DuplicateCheckResult`.
- `evadr.scan(url)` takes only the URL; `evadr.get_job_events` is replaced by `evadr.job_events` (an iterator of SSE events).
- Streams are plain iterators: `evadr.fetch_stream` and `webgrph.crawl_stream` (sync and async) yield events directly instead of an async context manager. `parlyr.chat_stream` on the async client keeps its context-manager form; the sync client gains `chat_stream` and the async client `chat`.
- `kolektr.page` no longer takes `limit`/`offset` (the API returns all records); `page_all` makes one request.
- Models: `DiscoverResult`, `DiscoverEvent`, `ApiEndpoint`, `FetchyrResult`, `MfaResult`, `DeduplicationResult` are removed; `MfaChallenge` and `DuplicateCheckResult` are added; the Nexus, workflow, form and session results carry the API's fields.

### Removed (no API route)
- `fetchyr.fetch` (use `evadr.fetch(url, session_artifact_id=...)`), `fetchyr.get_session`, `webgrph.get_hierarchy`, `webgrph.get_job`, and the skanyr discovery methods (`discover`, `discover_all`, `discover_stream`, `get_discovery`, `get_discovery_events`, `analyze_bundle`, `discover_page_live`, `hierarchy`, `expand_node`, `retry`, `health`, `get_api_map`, `get_job`).
- Moved from `skanyr` to `webgrph`: `reader_view`, `detected_apis` and the session methods.

### Added
- `evadr.fetch` follows a synchronous fetch the API hands off as a job (202 after ~85 s, below Cloudflare's 100 s limit) to its result; `poll_interval`, `poll_timeout`; `evadr.wait_for_job`.
- Typed errors: `PaymentRequiredError` (402), `QuotaExceededError` (429 `gb_exhausted`, not retried), `RateLimitError` (429, honours `Retry-After`), `BillingUnavailableError` (503, retried after `Retry-After`), `JobFailedError`, `JobTimeoutError`. Error messages read the API's `detail` object.
- `evadr.profile`, `fetchyr.resume_execution`, the auth-chain calls, `webgrph.start_crawl`, `cancel_crawl`, `crawl_events`, `crawl_all_pages`, `webgrph` sessions, the skanyr site store (sites, sync, export, resources, search, findings, technologies, snapshots, timeline, diff, graph, extraction), and `page_all` on the async client.

### Fixed
- Streams opened their own HTTP client and ignored the one passed to the SDK; they now go through the SDK's transport.
- `fetch_async` posted to the synchronous route with a stray `async` field; it uses `evadr/fetch/async`.

### Security
- `webgrph.crawl_stream` sent the API key as a URL query parameter; it is sent in the `Authorization` header.

## [0.2.0] — 2026-05-13

### Added
- Full API coverage for all 117 kernel module operations across 7 modules
- Evadr: `scan()`, `get_job()`, `get_job_events()`, `list_vendors()`, `list_profiles()`, `list_proxies()`, `delete_proxy()`
- Fetchyr: credential management (`store_credentials`, `list_credentials`, `delete_credentials`), session management (`list_sessions`, `terminate_session`), form automation (`fill_form`), MFA queue (`list_mfa_challenges`, `get_mfa_challenge`, `get_mfa_statistics`), workflow CRUD (`list_workflows`, `get_workflow`, `update_workflow`, `delete_workflow`, `get_workflow_statistics`), multi-site orchestration (`create_multi_site_workflow`), dedup sessions (`create_dedup_session`, `list_dedup_sessions`, `get_dedup_session`, `get_dedup_session_statistics`, `get_dedup_domain_statistics`)
- Kolektr: API data retrieval (`get_api_data`, `get_api_data_paginated`, `extract_all_api_data`), content management, job management with progress tracking, pipeline events, progress phases, scraper config CRUD
- Nexus: `reason()`, full recommendations subsystem (analyze, applications, cache management, hooks, preferences CRUD, statistics)
- Skanyr: `get_discovery()`, `get_discovery_events()`, `analyze_bundle()`, `discover_page_live()`, `detected_apis()`, `hierarchy()`, `expand_node()`, `reader_view()`, `retry()`, `health()`, session management CRUD
- Webgrph: `get_crawl_status()`, `get_crawl_events()`, `get_crawl_pages()`, full analytics subsystem (dashboard, errors, trends, discovery patterns, efficiency, site mapping, user behavior)
- HTTP transport: `put()` and `patch()` methods for full CRUD support

### Changed
- Fetchyr `check_duplicates()` now hits correct endpoint path `fetchyr/deduplication/check`

## [0.1.0] — 2026-04-09

### Added
- Initial release of the official KLOAKD Python SDK
- `Kloakd` synchronous client and `AsyncKloakd` async client
- 7 module namespaces: `evadr`, `webgrph`, `skanyr`, `nexus`, `parlyr`, `fetchyr`, `kolektr`
- `KloakdError` hierarchy: `AuthenticationError`, `NotEntitledError`, `RateLimitError`, `UpstreamError`, `ApiError`
- Exponential backoff retry logic (3 attempts, respects `Retry-After` header)
- Artifact chaining across all modules
- SSE streaming support: `evadr.fetch_stream()`, `webgrph.crawl_stream()`, `skanyr.discover_stream()`, `parlyr.chat_stream()`
- Pagination support (`limit`/`offset`) on all list-returning methods
- Auto-paginate helpers: `crawl_all()`, `discover_all()`, `page_all()`
- Fetchyr expanded methods: `create_workflow()`, `execute_workflow()`, `get_execution()`, `detect_forms()`, `detect_mfa()`, `submit_mfa()`, `check_duplicates()`
- Full type annotations (Python 3.9+)
- Test suite with respx mocks (~90% coverage)
