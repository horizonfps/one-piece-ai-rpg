"""Creation catalog API: read catalogs + trait roller. The roll lives in the backend so
it is testable and cheap to reroll (no LLM cost)."""
from __future__ import annotations

import random

from fastapi import APIRouter
from pydantic import BaseModel

from ..db import catalog
from ..db import connection
from ..pipeline import character_creation as cc

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("")
async def get_all() -> dict:
    """All three catalogs at once (the creation screen loads everything on mount)."""
    conn = await connection.connect()
    try:
        return {
            "traits": await catalog.get_traits(conn),
            "classes": await catalog.get_classes(conn),
            "fruits": await catalog.get_fruits(conn),
            "tiers": list(cc.TIERS),
        }
    finally:
        await conn.close()


@router.get("/traits")
async def get_traits() -> dict:
    conn = await connection.connect()
    try:
        return {"traits": await catalog.get_traits(conn)}
    finally:
        await conn.close()


@router.get("/classes")
async def get_classes() -> dict:
    conn = await connection.connect()
    try:
        return {"classes": await catalog.get_classes(conn)}
    finally:
        await conn.close()


@router.get("/fruits")
async def get_fruits() -> dict:
    conn = await connection.connect()
    try:
        return {"fruits": await catalog.get_fruits(conn)}
    finally:
        await conn.close()


class RollBody(BaseModel):
    seed: int | None = None         # deterministic for tests; default random
    count: int | None = None        # override the 1d4+1 roll; default rolls


@router.post("/roll-traits")
async def roll_traits(body: RollBody) -> dict:
    """Roll 1d4+1 traits with stacking-exclusion applied. Each reroll is a fresh call."""
    conn = await connection.connect()
    try:
        traits = await catalog.get_traits(conn)
    finally:
        await conn.close()
    rng = random.Random(body.seed)
    hand = cc.roll_traits(traits, rng, count=body.count)
    return {"traits": hand, "count": len(hand)}
