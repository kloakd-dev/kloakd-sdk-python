"""A fetch's stored page (the cost-control contract of 15 November 2026,
section 8): ``GET artifacts/{id}`` for its metadata and
``GET artifacts/{id}/content`` for the page itself."""

from __future__ import annotations

from typing import Any, Callable, Optional

from kloakd.models import Artifact
from kloakd.modules._ops import Op, _Op, as_dict, seg


def _int_or_none(value: Any) -> Optional[int]:
    return int(value) if value is not None else None


def _artifact(artifact_id: str) -> Callable[[Any], Artifact]:
    def parse(body: Any) -> Artifact:
        raw = as_dict(body)
        return Artifact(
            id=str(raw.get("id") or artifact_id),
            type=str(raw.get("type") or ""),
            url=raw.get("url"),
            created_at=raw.get("created_at"),
            size_bytes=_int_or_none(raw.get("size_bytes")),
            content_type=raw.get("content_type"),
            final_url=raw.get("final_url"),
            status_code=_int_or_none(raw.get("status_code")),
            verified=bool(raw.get("verified", False)),
            content_url=raw.get("content_url"),
        )

    return parse


def get_artifact_op(artifact_id: str) -> Op[Artifact]:
    return _Op("GET", f"artifacts/{seg(artifact_id)}", parse=_artifact(artifact_id))


def artifact_content_path(artifact_id: str) -> str:
    return f"artifacts/{seg(artifact_id)}/content"
