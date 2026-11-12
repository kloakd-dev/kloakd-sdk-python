"""The batch job and unified scrape operations of the client.

Read from kobe-scraper integration/2026-11-12b (228857dc):
kernel/jobs_runs_router.py (BatchJob, BatchJobsList, BatchJobResults and the
batch-jobs routes), application/jobs/batch_control.py (what pause, resume
and cancel allow) and api/v1/endpoints/unified_scraping.py. Each operation
is built once here and run by both clients (kloakd/modules/_ops.py).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from kloakd.models import (
    BatchJob,
    BatchJobItem,
    BatchJobResults,
    BatchJobsPage,
    UnifiedEscalation,
    UnifiedScrapeProgress,
    UnifiedScrapeResult,
    UnifiedScrapeStatus,
)
from kloakd.modules._ops import Op, _Op, as_dict, compact, seg


def _dicts(value: Any) -> List[Dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _dict_or_none(value: Any) -> Optional[Dict[str, Any]]:
    return value if isinstance(value, dict) else None


def parse_batch_job(raw: Any) -> BatchJob:
    data = as_dict(raw)
    return BatchJob(
        id=str(data.get("id") or ""),
        name=str(data.get("name") or ""),
        status=str(data.get("status") or ""),
        total_items=int(data.get("total_items") or 0),
        completed_items=int(data.get("completed_items") or 0),
        created_at=str(data.get("created_at") or ""),
        message=data.get("message"),
    )


def _parse_page(raw: Any) -> BatchJobsPage:
    data = as_dict(raw)
    return BatchJobsPage(
        total=int(data.get("total") or 0),
        batch_jobs=[parse_batch_job(job) for job in _dicts(data.get("batch_jobs"))],
    )


def _parse_results(batch_job_id: str, raw: Any) -> BatchJobResults:
    data = as_dict(raw)
    return BatchJobResults(
        batch_job_id=str(data.get("batch_job_id") or batch_job_id),
        results=[
            BatchJobItem(
                job_id=str(item.get("job_id") or ""),
                url=item.get("url"),
                status=str(item.get("status") or ""),
                extracted_data=item.get("extracted_data"),
                api_data=_dict_or_none(item.get("api_data")),
            )
            for item in _dicts(data.get("results"))
        ],
        total_jobs=int(data.get("total_jobs") or 0),
        completed_jobs=int(data.get("completed_jobs") or 0),
        failed_jobs=int(data.get("failed_jobs") or 0),
    )


def _escalations(value: Any) -> List[UnifiedEscalation]:
    return [
        UnifiedEscalation(
            from_level=str(step.get("from") or ""),
            to_level=str(step.get("to") or ""),
            reason=str(step.get("reason") or ""),
            timestamp=str(step.get("timestamp") or ""),
        )
        for step in _dicts(value)
    ]


def parse_unified_result(raw: Any) -> UnifiedScrapeResult:
    data = as_dict(raw)
    return UnifiedScrapeResult(
        success=data.get("success") is not False,
        job_id=str(data.get("job_id") or ""),
        level=str(data.get("level") or ""),
        status=str(data.get("status") or ""),
        escalation_path=_escalations(data.get("escalation_path")),
        message=str(data.get("message") or ""),
        metadata=_dict_or_none(data.get("metadata")),
        auth_required=data.get("auth_required") is True,
        discovery_id=data.get("discovery_id"),
    )


def _parse_unified_status(job_id: str, raw: Any) -> UnifiedScrapeStatus:
    data = as_dict(raw)
    detail = _dict_or_none(data.get("progress_detail"))
    partial = detail.get("partial_results") if detail else None
    return UnifiedScrapeStatus(
        id=str(data.get("id") or job_id),
        status=str(data.get("status") or ""),
        level=str(data.get("level") or ""),
        progress=data.get("progress"),
        progress_detail=None
        if detail is None
        else UnifiedScrapeProgress(
            percentage=int(detail.get("percentage") or 0),
            current_step=str(detail.get("current_step") or ""),
            items_found=detail.get("items_found"),
            items_target=detail.get("items_target"),
            partial_results=_dicts(partial) if isinstance(partial, list) else None,
        ),
        created_at=str(data.get("created_at") or ""),
        updated_at=data.get("updated_at"),
        completed_at=data.get("completed_at"),
        error=data.get("error"),
        result=_dict_or_none(data.get("result")),
        escalation_path=_escalations(data.get("escalation_path")),
    )


def create_batch_job_op(
    urls: List[str],
    extraction_config: Optional[Dict[str, Any]],
    crawl_id: Optional[str],
    entity_type: Optional[str],
    fields: Optional[List[str]],
) -> Op[BatchJob]:
    body = {
        "urls": list(urls),
        **compact(
            {
                "extraction_config": extraction_config,
                "crawl_id": crawl_id,
                "entity_type": entity_type,
                "fields": fields,
            }
        ),
    }
    return _Op("POST", "batch-jobs", body, parse=parse_batch_job)


def get_batch_job_op(batch_job_id: str) -> Op[BatchJob]:
    return _Op("GET", f"batch-jobs/{seg(batch_job_id)}", parse=parse_batch_job)


def list_batch_jobs_op(
    page: Optional[int], page_size: Optional[int]
) -> Op[BatchJobsPage]:
    params = compact({"page": page, "page_size": page_size})
    return _Op("GET", "batch-jobs", None, params or None, parse=_parse_page)


def batch_job_results_op(
    batch_job_id: str, limit: Optional[int], offset: Optional[int]
) -> Op[BatchJobResults]:
    params = compact({"limit": limit, "offset": offset})
    return _Op(
        "GET",
        f"batch-jobs/{seg(batch_job_id)}/results",
        None,
        params or None,
        parse=lambda raw: _parse_results(batch_job_id, raw),
    )


def batch_control_op(batch_job_id: str, action: str) -> Op[BatchJob]:
    """``action``: pause, resume or cancel."""
    return _Op(
        "POST", f"batch-jobs/{seg(batch_job_id)}/{action}", {}, parse=parse_batch_job
    )


def unified_scrape_body(
    url: str,
    prompt: Optional[str],
    mode: Optional[str],
    schema: Optional[Dict[str, str]],
    options: Optional[Dict[str, Any]],
    context: Optional[Dict[str, Any]],
    constraints: Optional[Dict[str, Any]],
    session_artifact_id: Optional[str],
) -> Dict[str, Any]:
    """The body of ``POST scraping/unified`` (UnifiedScrapeRequest): the URL
    and only the fields given."""
    return {
        "url": url,
        **compact(
            {
                "prompt": prompt,
                "mode": mode,
                "schema": schema,
                "options": options,
                "context": context,
                "constraints": constraints,
                "session_artifact_id": session_artifact_id,
            }
        ),
    }


def get_unified_scrape_op(job_id: str) -> Op[UnifiedScrapeStatus]:
    return _Op(
        "GET",
        f"scraping/unified/{seg(job_id)}",
        parse=lambda raw: _parse_unified_status(job_id, raw),
    )
