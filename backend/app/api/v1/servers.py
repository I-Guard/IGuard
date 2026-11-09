from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal, client_ip, get_integrations, require_admin, require_viewer
from app.core.errors import ConflictError
from app.database.session import get_db
from app.integrations import Integrations
from app.models import Server, Service
from app.monitoring import prometheus as pq
from app.monitoring.prometheus import PrometheusClient
from app.repositories.base import paginate
from app.repositories.domain import ServerRepository
from app.schemas.common import Page, PageParams
from app.schemas.infra import ServerCreate, ServerOut, ServerUpdate
from app.services import audit, overview_service
from app.services.presenters import server_out

router = APIRouter(prefix="/servers", tags=["servers"])


def _present(db: Session, prom: PrometheusClient, servers: list[Server]) -> list[ServerOut]:
    up = overview_service.node_up_map(prom)
    counts = overview_service.active_incident_counts(db)
    svc_counts = dict(
        db.execute(select(Service.server_id, func.count()).group_by(Service.server_id)).all()
    )
    return [
        server_out(
            s,
            overview_service.server_health(s, up, counts.get(s.id, {})),
            sum(counts.get(s.id, {}).values()),
            int(svc_counts.get(s.id, 0)),
        )
        for s in servers
    ]


@router.get("", response_model=Page[ServerOut])
def list_servers(
    params: PageParams = Depends(),
    search: str | None = Query(None, max_length=100),
    environment: str | None = Query(None, max_length=32),
    sort: str | None = Query(None, description="name|hostname|created_at, prefix '-' for desc"),
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    _: Principal = Depends(require_viewer),
) -> Page[ServerOut]:
    rows, total = paginate(db, ServerRepository(db).list(search, environment, sort), params)
    return Page.build(_present(db, integ.prometheus, rows), total, params.page, params.page_size)


@router.post("", response_model=ServerOut, status_code=201)
def create_server(
    body: ServerCreate,
    request: Request,
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    principal: Principal = Depends(require_admin),
) -> ServerOut:
    server = Server(**body.model_dump())
    try:
        with db.begin_nested():
            db.add(server)
            db.flush()
    except IntegrityError as exc:
        raise ConflictError(f"A server named '{body.name}' already exists") from exc
    audit.record(
        db,
        action="server.create",
        resource_type="server",
        resource_id=server.id,
        actor=principal.user,
        ip=client_ip(request),
        details={"name": server.name},
    )
    return _present(db, integ.prometheus, [server])[0]


@router.get("/{server_id}", response_model=ServerOut)
def get_server(
    server_id: uuid.UUID,
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    _: Principal = Depends(require_viewer),
) -> ServerOut:
    server = ServerRepository(db).get_or_404(server_id)
    return _present(db, integ.prometheus, [server])[0]


@router.get("/{server_id}/metrics", summary="Live host metrics from Prometheus/node-exporter")
def server_metrics(
    server_id: uuid.UUID,
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    _: Principal = Depends(require_viewer),
) -> dict:
    server = ServerRepository(db).get_or_404(server_id)
    if not server.prometheus_instance:
        return {"available": False, "reason": "No Prometheus instance configured for this server"}
    data = pq.node_metrics(integ.prometheus, server.prometheus_instance)
    has_any = any(
        v is not None
        for k, v in data.items()
        if k not in ("instance", "host") and not isinstance(v, list)
    )
    return {
        "available": has_any,
        "metrics": data,
        "reason": None if has_any else "Prometheus returned no data for this instance",
    }


@router.get("/{server_id}/metrics/range", summary="Time series for a metric")
def server_metrics_range(
    server_id: uuid.UUID,
    metric: Annotated[str, Query(pattern="^(cpu|memory|disk|network_rx|network_tx|load1)$")],
    minutes: Annotated[int, Query(ge=5, le=1440)] = 60,
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    _: Principal = Depends(require_viewer),
) -> dict:
    import time

    server = ServerRepository(db).get_or_404(server_id)
    if not server.prometheus_instance:
        return {"metric": metric, "series": []}
    end = time.time()
    step = max(15, minutes * 60 // 240)
    expr = pq.RANGE_QUERIES[metric] % pq.instance_selector(server.prometheus_instance)
    return {
        "metric": metric,
        "step": step,
        "series": integ.prometheus.query_range(expr, end - minutes * 60, end, step),
    }


@router.patch("/{server_id}", response_model=ServerOut)
def update_server(
    server_id: uuid.UUID,
    body: ServerUpdate,
    request: Request,
    db: Session = Depends(get_db),
    integ: Integrations = Depends(get_integrations),
    principal: Principal = Depends(require_admin),
) -> ServerOut:
    server = ServerRepository(db).get_or_404(server_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(server, k, v)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A server with that name already exists") from exc
    audit.record(
        db,
        action="server.update",
        resource_type="server",
        resource_id=server.id,
        actor=principal.user,
        ip=client_ip(request),
        details={"fields": sorted(changes)},
    )
    return _present(db, integ.prometheus, [server])[0]


@router.delete("/{server_id}", status_code=204)
def delete_server(
    server_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_admin),
) -> Response:
    server = ServerRepository(db).get_or_404(server_id)
    name = server.name
    ServerRepository(db).delete(server)
    audit.record(
        db,
        action="server.delete",
        resource_type="server",
        resource_id=server_id,
        actor=principal.user,
        ip=client_ip(request),
        details={"name": name},
    )
    return Response(status_code=204)
