# Changelog

All notable changes to `kloakd-sdk` are documented here.

Format: [Semantic Versioning](https://semver.org/). Types: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.

---

## [Unreleased]

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
