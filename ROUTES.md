# Routes the SDK calls (0.4.0)

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
| GET | webgrph/analytics/... (the other five) | not called: the dashboard's sub-router, not part of the public API (`get_dashboard_summary`, `get_discovery_patterns`, `get_efficiency_metrics`, `get_site_mapping_trends`, `get_user_behavior_insights` removed) |
| GET | evadr/profiles | removed (`list_profiles`). GET evadr/vendors stays |
| * | recommendations/... (standalone router) | dropped from the route list: not mounted (`api/app.py`, GAP-SEC-6) |
| POST | nexus/execute | response read for `execution_result_id` |

# Routes the SDK called in 0.3.0

Checked against the API's route list (`tests/fixtures/routes.tsv`, generated
from kobe-scraper 4fb33ea4 with the module routers mounted as
`kernel/bootstrap.py` does). `tests/test_contract.py` calls every public
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
| GET | fetchyr/sessions/{id} | removed | `get_session` dropped (list and delete remain) |
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

Not covered: `GET skanyr/resources/{id}/download` (binary body) and
`GET parlyr/chat/{id}/events`.
