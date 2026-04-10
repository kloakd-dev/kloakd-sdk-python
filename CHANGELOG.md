# Changelog

All notable changes to `kloakd-sdk` are documented here.

Format: [Semantic Versioning](https://semver.org/). Types: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.

---

## [Unreleased]

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
