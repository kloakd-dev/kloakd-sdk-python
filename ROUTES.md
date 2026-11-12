# Routes the SDK calls (0.7.0)

## Batch jobs and the unified scrape

Checked against kobe-scraper integration/2026-11-12b (228857dc):
`kernel/jobs_runs_router.py`, `application/jobs/batch_control.py` and
`api/v1/endpoints/unified_scraping.py`. `tests/fixtures/routes.tsv` is
generated from that checkout: 280 rows. The 12 `performance/...` routes are
gone from the API; the SDK called none of them.
`tests/test_batch_unified.py` checks the new calls against the list.

| Method | Path | 0.7.0 |
|---|---|---|
| POST | batch-jobs | new: `client.create_batch_job`; body `{urls, extraction_config?, crawl_id?, entity_type?, fields?}`; 201; 403 `test_key_not_allowed`, 409 `concurrent_limit`, 413 `batch_too_large`, 422 for no URLs, 503 `dispatch_failed` |
| GET | batch-jobs | new: `client.list_batch_jobs`; `page`, `page_size` (1-100) |
| GET | batch-jobs/{batch_job_id} | new: `client.get_batch_job` |
| GET | batch-jobs/{batch_job_id}/results | new: `client.get_batch_job_results`; `limit` (1-1000), `offset`; each item is `{job_id, url, status, extracted_data, api_data}` |
| POST | batch-jobs/{batch_job_id}/pause | new: `client.pause_batch_job`; only a running batch; a paused one answers 200 unchanged; otherwise 409 `invalid_batch_transition` |
| POST | batch-jobs/{batch_job_id}/resume | new: `client.resume_batch_job`; only a paused batch; a running one answers 200 unchanged; otherwise 409 `invalid_batch_transition`; 409 `concurrent_limit`; 503 `dispatch_failed` (paused again) |
| POST | batch-jobs/{batch_job_id}/cancel | new: `client.cancel_batch_job`; a cancelled one answers 200 unchanged; 409 `invalid_batch_transition` once completed or failed |
| POST | scraping/unified | new: `client.unified_scrape`; body `{url, prompt?, mode?, schema?, options?, context?, constraints?, session_artifact_id?}`; a 202 hand-off is followed through `GET handoff/{job_id}`; 403 `test_key_not_allowed`, `module_not_entitled` |
| GET | scraping/unified/{job_id} | new: `client.get_unified_scrape` |

Not covered, by choice: `DELETE batch/{batch_job_id}`, `POST
batch/url-import` and the event stream `GET
batch-jobs/{batch_job_id}/stream`. There is no batch waiter.

## Changed in 0.7.0

Checked against kobe-scraper 6bd19e9b (main, 12 November 2026). The route
list in `tests/fixtures/routes.tsv` was then generated again from that commit
(292 rows; 280 since integration/2026-11-12b, see above: every route of `kobe_scraper.api.app` with the module routers,
the crawl-extract router and the playground and free-tier routers mounted
as `kernel/bootstrap.py` does). `tests/test_contract.py` calls every public
method of the sync and the async client and fails on any request that is
not in the list.

| Method | Path | 0.7.0 |
|---|---|---|
| POST | nexus/execute | removed from the API (`modules/nexus/router.py`) and the SDK (`nexus.execute`) |
| POST | nexus/knowledge | no longer called (`nexus.knowledge` removed): the body is now `{strategy_id, url, outcome}` and the route is left out of the public API reference (`scripts/generate_public_openapi.py` EXCLUDED). Still in the route list |
| POST | nexus/verify | response read for `status`, `risk_score`, `safety_checks`, `verification_result_id`, `duration_ms` as well (VerifyResponse) |
| POST | webgrph/crawl-extract | `webgrph.start_crawl_extract`, `crawl_extract` (`modules/webgrph/crawl_extract_router.py`) |
| GET | webgrph/crawl-extract/{job_id} | `get_crawl_extract`, `wait_for_crawl_extract` |
| GET | webgrph/crawl-extract/{job_id}/results | `get_crawl_extract_results`, `iter_crawl_extract_results`, `crawl_extract_all_results`: `limit` (1-1000), `cursor`, `shape`, `page_type`, `kind` |
| GET | webgrph/crawl-extract/{job_id}/pages | `get_crawl_extract_pages`: `limit`, `offset`, `status` |
| GET | webgrph/crawl-extract/{job_id}/export | `export_crawl_extract`, `download_crawl_extract`: `format` (json, ndjson, csv), `shape`, `page_type`, `kind`; streamed |
| POST | webgrph/crawl-extract/{job_id}/cancel | `cancel_crawl_extract` |
| GET | webgrph/crawl-extract/{job_id} | also read for `crawl` (what the job's crawl did; `modules/webgrph/crawl_extract.py` crawl_truth). `wait_for_crawl_extract` and `crawl_extract` return a job whose `crawl.status` is `held_quota` (`held`) |
| GET | webgrph/crawl-extract/{job_id}/export | also read for the `X-Crawl-*` headers (`ExportDownload.crawl`, `SavedExport.crawl`; `crawl_extract_router.py` _crawl_headers) |
| GET | batch-jobs/{batch_job_id}/export | `client.export_batch_job`, `download_batch_job`: `format`; streamed (`kernel/batch_export_router.py`). Sends no `X-Job-Status` and no `X-Crawl-*` header: `job_status` and `crawl` are None |
| POST | webgrph/crawl/{crawl_id}/continue | new: `webgrph.continue_crawl` (202 `{success, crawl_id, status}`; 409 when the crawl cannot be continued; `modules/webgrph/router.py`) |
| GET | webgrph/crawl/{crawl_id} | also called by the new `webgrph.wait_for_crawl`. Read for `is_partial`, `partial_reason`, `resumable`, `pages_discovered`, `pages_fetched`, `pages_unfetched`, `error_code`, `message` as well (CrawlStatusResponse). Status `held_quota` ends the wait (`CrawlResult.held`) and is not an error |
| POST | webgrph/crawl | `max_depth` and `max_pages` sent only when given (CrawlRequest: the plan's default applies) |
| GET | webgrph/crawl/{crawl_id}/pages | nodes read for `metadata.fetch_status` and `metadata.fetch_error`; `PageNode.status_code` and `crawl_parent_url` removed (the listing sends neither) |
| POST | fetchyr/login-sessions | new: `fetchyr.start_login_session` (`{target_url, method?, cookies?, user_agent?, country?}`; 201 for cookies, 202 for interactive; `modules/fetchyr/router.py`) |
| GET | fetchyr/sessions/{artifact_id} | new: `fetchyr.get_session` (SessionStatusResponse). The 0.3.0 table below says this route was removed; it is live again, with a different answer |
| POST | fetchyr/sessions/{artifact_id}/resume | new: `fetchyr.resume_session` (409 when not paused or signed out) |
| GET | skanyr/extractions/{hash}/text | the text/plain body is returned as it is (it was parsed as JSON first: a body such as `123` or `{"a": 1}` did not come back as text) |
| POST | kolektr/extract | response read for `level`, `level_reason`, `login_options`; `has_more` and `total` are no longer read (ExtractResponse has neither) |
| POST | nexus/analyze, synthesize, verify | `error` is no longer read (no answer has it) |
| POST | nexus/reason | `timeout_secs` may be a fraction (ReasonRequest: float) |

## Routes in the list the SDK does not call

Under the seven namespaces, three: `GET skanyr/resources/{id}/download`
(binary body), `GET parlyr/chat/{id}/events`, and `POST nexus/knowledge`
(left out of the public API reference).

Outside the namespaces the SDK calls `GET handoff/{job_id}`, the
`batch-jobs` routes except the event stream, and `scraping/unified` with
its job read. Not covered: `GET batch-jobs/{batch_job_id}/stream`,
`batch/*`, `jobs`, `results`, `webhooks` (deliveries, retry and
rotate-secret included), `activity`, `scrapers`, the other `scraping`
routes, `screenshots`, `pipeline`, `analysis`, `analytics`, `monitoring`,
`integrations`, `workspaces`, `users`, `members`, and everything outside
`/api/v1/organizations/{organization_id}/` (auth, billing, free, playground,
ops, system, health, invitations). The five `webgrph/analytics/*` routes
that earlier lists carried are not in the API any more.

# Routes the SDK called in 0.6.0

## Changed in 0.6.0

Checked against kobe-scraper main 1c74de2b (deployed 0bb0c6b5, 2 November
2026). No route was added or removed.

| Method | Path | 0.6.0 |
|---|---|---|
| POST | kolektr/extract, kolektr/extract/html | `schema_spec.item_selector` (`item_selector=` on `page`, `page_all`, `extract_html`); fields may carry `attribute` and `type` (`modules/kolektr/router.py` SchemaSpec, GAP-API-11) |
| GET | webgrph/crawl/{crawl_id}/pages | `include_grouping` (sent as `true` only when asked); `limit` checked 1-1000 and `cursor` checked as a non-negative integer before the request; nodes read for `parent_url` and `metadata.is_grouping` (`modules/webgrph/router.py` get_crawl_pages, GAP-API-9/10) |
| * | every metered route | 409 `concurrent_limit` read for `active_requests` as well (`kernel/gateway/dependencies.py` hold_work_slot, GAP-BILL-13); not retried |

# Routes the SDK called in 0.5.0

## Changed in 0.5.0

Checked against kobe-scraper e5f15f7d. No route was added or removed; these
calls changed what they send or how they read the answer. Every path
segment is now percent-encoded (encodeURIComponent-style).

| Method | Path | 0.5.0 |
|---|---|---|
| GET | handoff/{job_id} | now public: `client.get_handoff`, `client.wait_for_handoff` (`kernel/sync_handoff.py`) |
| POST | parlyr/chat | events read as `{type, content, data, actions, timestamp}` up to `end` (`application/services/chat_orchestrator.py`) |
| POST | nexus/reason | `parameters` is a list of strings (`modules/nexus/router.py` ReasonRequest) |
| PATCH | skanyr/sites/{site_id} | `policy` is a string (`modules/skanyr/router.py` SiteUpdateRequest) |
| GET | skanyr/sites/{id}/apis, /resources, /findings, /technologies, skanyr/resources | parsed as lists |
| POST | skanyr/sites/{site_id}/export | returns the ZIP bytes |
| GET | skanyr/extractions/{hash}/text | returns the text (the route answers text/plain) |
| POST | fetchyr/multi-site-workflows | `dependencies` is a list (`modules/fetchyr/router.py` SiteDependencyModel) |
| GET | kolektr/jobs | `page`, `limit`, `status_filter` |
| GET | kolektr/scrapers | `page`, `page_size`, `is_template` |
| GET | kolektr/content | `page`, `page_size`, `search` |
| GET | fetchyr/workflows | `page`, `page_size` |
| GET | kolektr/api-data/{api_endpoint:path}[/paginated] | `endpoint_hash`; the endpoint URL is one encoded segment |
| POST | kolektr/api-data/{api_endpoint:path}/extract-all | `endpoint_hash`, `max_records` (query) |
| GET | webgrph/sessions | `active_only` always sent (default true) |

# Routes the SDK called in 0.4.0

## Changed in 0.4.0

Checked against kobe-scraper: the hand-off decorator `@hands_off_after_limit`
(`kernel/sync_handoff.py`, on main since 5bc47e8d) and the route removals of
branch `fix/stubs-and-knowledge` (d7d25134, 00ee9f34). The route list in
`tests/fixtures/routes.tsv` was edited to match (rows removed, the poll route
added), not regenerated.

| Method | Path | 0.4.0 |
|---|---|---|
| POST | kolektr/extract, fetchyr/authenticate, fetchyr/form/detect, fetchyr/form/fill, fetchyr/mfa/detect, nexus/analyze, nexus/synthesize, nexus/execute | a 202 hand-off is followed to the result |
| GET | handoff/{job_id} | the poll the hand-off routes name in `poll_url` (added to the route list) |
| POST | evadr/fetch | the 202 is followed through its own `poll_url` (evadr/jobs/{id}), with the same follower |
| * | nexus/recommendations/... (13 routes) | removed from the API and the SDK (invented results, GAP-API-3) |
| POST | kolektr/jobs | removed (`create_job`; GAP-API-2). GET kolektr/jobs and jobs/{id} stay |
| GET | kolektr/jobs/{id}/progress[/summary, /events, /latest] | removed (`get_job_progress*`) |
| GET | kolektr/progress/phases[/{name}[/steps]], progress/summary | removed (`list_progress_phases`, `get_progress_phase`, `get_progress_phase_steps`, `get_progress_summary`) |
| GET | kolektr/pipeline/{id}/stream, /events | removed (`get_pipeline_stream`, `get_pipeline_events`) |
| GET | webgrph/analytics/job-trends, error-summary | removed (`get_job_trends`, `get_error_summary`) |
| GET | webgrph/analytics/... (the other five; gone from the API at 6bd19e9b) | not called: the dashboard's sub-router, not part of the public API (`get_dashboard_summary`, `get_discovery_patterns`, `get_efficiency_metrics`, `get_site_mapping_trends`, `get_user_behavior_insights` removed) |
| GET | evadr/profiles | removed (`list_profiles`). GET evadr/vendors stays |
| * | recommendations/... (standalone router) | dropped from the route list: not mounted (`api/app.py`, GAP-SEC-6) |
| POST | nexus/execute | response read for `execution_result_id` |

# Routes the SDK called in 0.3.0

Checked against the API's route list (`tests/fixtures/routes.tsv`, at 0.3.0
generated from kobe-scraper 4fb33ea4 with the module routers mounted as
`kernel/bootstrap.py` does; the list in the repository now is the one
generated from 6bd19e9b, see the top). `tests/test_contract.py` calls every public
method of the sync and the async client and fails on any request that is not a live route.

All paths are under `/api/v1/organizations/{organization_id}/`.

## What 0.2.0 called

| Method | Path (0.2.0) | Status | 0.3.0 |
|---|---|---|---|
| POST | evadr/fetch | live | `fetch` follows a 202 job hand-off |
| POST | evadr/fetch (`async: true`) | wrong path | `fetch_async` → POST evadr/fetch/async |
| POST | evadr/fetch/stream | removed | `fetch_stream` = fetch/async + GET evadr/jobs/{id}/events |
| POST | evadr/analyze | live | unchanged |
| POST | evadr/scan | wrong fields | body is `{url}` only |
| GET | evadr/jobs/{id} | live | unchanged |
| GET | evadr/jobs/{id}/events | live, read as JSON | `job_events` streams it (SSE) |
| GET | evadr/vendors, profiles, proxies | live | unchanged |
| POST/DELETE | evadr/proxies[/{name}] | live | unchanged |
| POST | fetchyr/login | wrong path and fields | `authenticate(credential_name, target_url)` → POST fetchyr/authenticate |
| POST | fetchyr/fetch | removed | use `evadr.fetch(url, {session_artifact_id})` |
| GET | fetchyr/sessions/{id} | removed | `get_session` dropped (list and delete remain). Live again at 6bd19e9b for login sessions: `get_session` is back, see the top |
| DELETE | fetchyr/sessions/{id} | live | unchanged |
| POST | fetchyr/workflows | wrong fields (`url`) | `{name, steps, description?, workflow_type?}`; reads `id` |
| POST | fetchyr/workflows/{id}/execute | wrong fields (empty body) | `{target_url, session_artifact_id?, input_data?}` |
| GET | fetchyr/workflows/{id}/executions/{id} | live | reads `result` |
| POST | fetchyr/detect-forms | wrong path | POST fetchyr/form/detect |
| POST | fetchyr/detect-mfa | wrong path | POST fetchyr/mfa/detect |
| POST | fetchyr/submit-mfa | wrong path and fields | POST fetchyr/mfa-queue/{id}/resolve `{resolution}` |
| POST/GET/DELETE | fetchyr/account/credentials | live (fields loose) | `{name, username, password, extra?}` |
| GET | fetchyr/sessions, mfa-queue, mfa/challenges/{id}, mfa/statistics/{domain} | live | unchanged |
| POST | fetchyr/form/fill | wrong field (`submit`) | `{url, form_data, session_artifact_id?}` |
| GET/PATCH/DELETE | fetchyr/workflows[/{id}][/statistics] | live | PATCH sends the API's fields |
| POST | fetchyr/multi-site-workflows | wrong fields (`name` optional) | `name` required |
| POST | fetchyr/deduplication/check | wrong fields (`records`) | `check_duplicate(url, {content_hash?, session_id?})` |
| POST | fetchyr/deduplication/sessions | wrong fields | `{name, strategy?}` |
| GET | fetchyr/deduplication/... | live | unchanged |
| POST | kolektr/extract | wrong fields (`limit`, `offset`) | no paging fields |
| GET/POST | kolektr/api-data/..., content, jobs, extraction-jobs, pipeline, progress, scrapers | live | unchanged (`kolektr/jobs` POST is a server stub: GAP-API-2) |
| POST | nexus/analyze | wrong fields (`html` optional) | `analyze(url, html, opts)` |
| POST | nexus/synthesize | wrong fields (`perception_id`) | `synthesize(url, html, goal)` |
| POST | nexus/verify, execute, knowledge | live, response read wrongly | response fields fixed |
| POST | nexus/reason | wrong fields (free body) | `reason(query_type, parameters)` |
| * | nexus/recommendations/... | live | unchanged (server-side many are broken: GAP-SEC-6) |
| POST/DELETE | parlyr/parse, chat, chat/{id} | live | unchanged |
| POST | skanyr/discover, discover/stream | removed | discovery is `webgrph.crawl` |
| GET | skanyr/discover/{id}[/events] | removed | — |
| POST | skanyr/analyze-bundle, discover-page/live, hierarchy, expand-node, retry | removed | — |
| GET | skanyr/health, api-map/{id}, jobs/{id} | removed | — |
| GET | skanyr/detected-apis | moved | `webgrph.detected_apis` |
| POST | skanyr/reader-view | moved | `webgrph.reader_view` |
| * | skanyr/sessions[...] | moved | `webgrph.list_sessions/save_session/get_session/delete_session/end_session/update_session_job` |
| POST | webgrph/crawl | live, stray `limit`/`offset` fields | `crawl` waits for the crawl and pages its nodes by cursor; `wait=False` for the id only |
| GET | webgrph/crawl/{id}/events | live, API key in the URL (`?token=`) | `crawl_stream` sends the key in the `Authorization` header |
| GET | webgrph/crawl/{id}, events, pages | live | events streamed; pages by cursor |
| GET | webgrph/hierarchy/{id}, jobs/{id} | removed | use `get_crawl_pages` / `get_crawl_status` |
| GET | webgrph/analytics/... | live | unchanged |

Counts: 252 call sites in 0.2.0 (126 in each of the sync and the async
client). Per client: about 79 already right; 22 fixed (path, method, request
or response fields); 25 removed or moved (17 with no route, 8 moved from
skanyr to webgrph).

Differences from the TypeScript SDK's 0.2.0: Python already sent the
extraction schema as `schema_spec` (only the stray `limit`/`offset` were
wrong), and `webgrph.crawl` already polled the crawl and read its pages.
`webgrph.crawl_stream` put the API key in the URL (`?token=`), where proxies
and logs keep it; streams now send it in the `Authorization` header.

## Added in 0.3.0 (live routes the SDK did not cover)

`evadr.profile`, `evadr.wait_for_job`, `fetchyr.resume_execution`, the
`fetchyr` auth-chain calls, `webgrph.cancel_crawl`, `webgrph.crawl_events`,
`webgrph.crawl_all_pages`, and the `skanyr` site store: sites, sync, export,
APIs, resources, search, findings, technologies, snapshots, timeline, diff,
graph, extraction text and structure.

Not covered at 0.3.0: `GET skanyr/resources/{id}/download` (binary body) and
`GET parlyr/chat/{id}/events`. The list for the current code, with the
crawl continue and login-session routes now called, is at the top ("Routes
in the list the SDK does not call").
