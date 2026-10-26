"""Fault switches for demos (plan §2). Mounted only when ENABLE_FAULT_INJECTION is true, which the
settings refuse in production, so these routes do not exist there."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.problems import ProblemError
from app.core.faults import DEFAULT_TTL_S, FAULTS, MAX_TTL_S, Faults

router = APIRouter(prefix="/api/admin/faults", tags=["admin"])


class SwitchOn(BaseModel):
    ttl_s: int = Field(default=DEFAULT_TTL_S, ge=1, le=MAX_TTL_S, description="Turns itself off after this")


def _faults(request: Request) -> Faults:
    return Faults(request.app.state.redis, enabled=True)


def _known(name: str) -> str:
    if name not in FAULTS:
        raise ProblemError(404, "UNKNOWN_FAULT", "Unknown fault", f"available: {', '.join(FAULTS)}")
    return name


@router.get("")
async def list_faults(request: Request) -> dict[str, Any]:
    active = await _faults(request).status()
    return {"available": list(FAULTS), "active": [{"name": n, "expires_in_s": t} for n, t in active.items()]}


@router.put("/{name}")
async def switch_on(name: str, request: Request, body: SwitchOn | None = None) -> dict[str, Any]:
    ttl = (body or SwitchOn()).ttl_s
    await _faults(request).switch_on(_known(name), ttl)
    return {"name": name, "active": True, "expires_in_s": ttl}


@router.delete("/{name}")
async def switch_off(name: str, request: Request) -> dict[str, Any]:
    await _faults(request).switch_off(_known(name))
    return {"name": name, "active": False}


@router.delete("")
async def switch_all_off(request: Request) -> dict[str, Any]:
    await _faults(request).switch_off()
    return {"active": []}
