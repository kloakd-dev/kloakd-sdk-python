"""One description per API operation, run by the sync and the async namespaces.

Each namespace method builds an operation (method, path, body, query,
parser) and runs it through the transport, so the synchronous and
asynchronous clients cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar, cast, overload
from urllib.parse import quote

T = TypeVar("T")


@dataclass(frozen=True)
class Op(Generic[T]):
    method: str
    path: str
    body: Optional[Dict[str, Any]]
    params: Optional[Dict[str, Any]]
    parse: Callable[[Any], T]
    follow: bool = False


def as_dict(raw: Any) -> Dict[str, Any]:
    """A JSON object response (an empty one when the API sent none)."""
    return cast(Dict[str, Any], raw) if isinstance(raw, dict) else {}


def as_list(raw: Any) -> List[Dict[str, Any]]:
    """A JSON array response (an empty one when the API sent none)."""
    return cast(List[Dict[str, Any]], raw) if isinstance(raw, list) else []


@overload
def _Op(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = ...,
    params: Optional[Dict[str, Any]] = ...,
    *,
    follow: bool = ...,
) -> Op[Dict[str, Any]]: ...


@overload
def _Op(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = ...,
    params: Optional[Dict[str, Any]] = ...,
    *,
    parse: Callable[[Any], T],
    follow: bool = ...,
) -> Op[T]: ...


def _Op(
    method: str,
    path: str,
    body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    *,
    parse: Optional[Callable[[Any], Any]] = None,
    follow: bool = False,
) -> Op[Any]:
    """``follow``: the route may hand off as a job (202); follow it to the
    result (kloakd/_handoff.py)."""
    return Op(method, path, body, params, parse or as_dict, follow)


def seg(value: Any) -> str:
    """One URL path segment, percent-encoded (``/`` and ``?`` included), as
    encodeURIComponent does. The API decodes it before routing, so a value
    such as an API endpoint URL arrives whole."""
    return quote(str(value), safe="")


def compact(values: Dict[str, Any]) -> Dict[str, Any]:
    """The entries whose value is not None (optional fields left out)."""
    return {k: v for k, v in values.items() if v is not None}


def run(transport: Any, op: Op[T]) -> T:
    if op.follow:
        return op.parse(transport.post_following(op.path, op.body))
    return op.parse(
        transport.request(op.method, op.path, json_body=op.body, params=op.params)
    )


async def arun(transport: Any, op: Op[T]) -> T:
    if op.follow:
        return op.parse(await transport.post_following(op.path, op.body))
    return op.parse(
        await transport.request(op.method, op.path, json_body=op.body, params=op.params)
    )
