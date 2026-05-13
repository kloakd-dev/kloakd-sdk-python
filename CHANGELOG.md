# Changelog

All notable changes to `kloakd-sdk` are documented here.

Format: [Semantic Versioning](https://semver.org/). Types: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.

---

## [Unreleased]

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
