"""本地点位检索（加点工作台）：`GET /api/pois`。

数据源是本地 `poi_knowledge`（无外部 API、无 key、无配额），
口径与 Agent 生成时引用的权威库同源（见 app/services/poi_search.py）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import AuthUser
from app.api.security import enforce_business_auth
from app.common.envelope import ApiError, ok
from app.services import poi_search
from app.services.poi_search import CATEGORY_LABELS

router = APIRouter(
    prefix="/api/pois",
    tags=["pois"],
    dependencies=[Depends(enforce_business_auth)],
)


@router.get("")
def list_pois(
    city: str = Query(..., min_length=1, description="目的地城市（本地库内城市名）"),
    keywords: str | None = Query(None, description="名称/标签/描述关键词；留空则按评分取该城前 30"),
    category: str | None = Query(None, description="attraction|food|hotel"),
    user: AuthUser | None = Depends(enforce_business_auth),
) -> dict:
    if category and category not in CATEGORY_LABELS:
        raise ApiError(400, "未知的点位类别")
    return ok(poi_search.search_local(city, keywords=keywords or "", category=category))
