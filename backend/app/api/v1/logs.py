from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import Principal, get_integrations, require_viewer
from app.integrations import Integrations
from app.monitoring.loki import build_query
from app.schemas.ops import LogEntry

router = APIRouter(prefix="/logs", tags=["logs"])


def _run(
    integ: Integrations,
    *,
    service: str | None,
    container: str | None,
    level: str | None,
    q: str | None,
    regex: bool,
    since: datetime | None,
    until: datetime | None,
    limit: int,
    direction: str,
) -> list[LogEntry]:
    query = build_query({"service": service, "container": container, "level": level}, q, regex)
    rows = integ.loki.query_range(query, since, until, limit, direction)
    return [LogEntry(**r) for r in rows]


@router.get("", response_model=list[LogEntry], summary="Recent logs from Loki")
def logs(
    service: str | None = None,
    container: str | None = None,
    level: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    direction: Annotated[str, Query(pattern="^(backward|forward)$")] = "backward",
    integ: Integrations = Depends(get_integrations),
    _: Principal = Depends(require_viewer),
) -> list[LogEntry]:
    return _run(
        integ,
        service=service,
        container=container,
        level=level,
        q=None,
        regex=False,
        since=since,
        until=until,
        limit=limit,
        direction=direction,
    )


@router.get("/search", response_model=list[LogEntry], summary="Full-text / regex log search")
def search(
    q: Annotated[str, Query(min_length=1, max_length=200)],
    regex: bool = False,
    service: str | None = None,
    container: str | None = None,
    level: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    integ: Integrations = Depends(get_integrations),
    _: Principal = Depends(require_viewer),
) -> list[LogEntry]:
    return _run(
        integ,
        service=service,
        container=container,
        level=level,
        q=q,
        regex=regex,
        since=since,
        until=until,
        limit=limit,
        direction="backward",
    )
