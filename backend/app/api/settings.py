"""App preferences API, separate from the save. GET returns the public view (masked key);
PUT applies a partial patch that takes effect at runtime (proxy url/key without restart)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from .. import app_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsPatch(BaseModel):
    theme: str | None = None
    language: str | None = None
    proxy_url: str | None = None
    proxy_key: str | None = None
    auto_spawn_proxy: bool | None = None
    setup_completed: bool | None = None


@router.get("")
async def get_settings() -> dict:
    return app_settings.public_view()


@router.put("")
async def update_settings(body: SettingsPatch) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    app_settings.update(patch)
    return app_settings.public_view()
