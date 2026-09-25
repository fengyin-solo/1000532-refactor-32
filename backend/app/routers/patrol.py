"""巡视检查接口：维护巡视单，覆盖派发巡视、提交结果、作废巡视等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.patrol import PatrolService

router = APIRouter(prefix="/api/patrol", tags=["巡视检查"])

service = PatrolService()

LIST_FIELDS = ["巡视单号", "巡视路线", "巡视人员", "巡视日期", "发现问题数", "整改项数", "巡视时长", "巡视状态"]
STATUSES = ["待派发", "巡视中", "已提交", "已作废"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按巡视单号检索"),
    status: str | None = Query(default=None, description="待派发、巡视中、已提交、已作废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按巡视单号与状态过滤巡视检查列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def patrol_stats(month: str | None = Query(default=None, description="按月份统计，格式 YYYY-MM，默认本月")) -> dict[str, Any]:
    """巡视合计：发现问题、整改项与超时巡视共用列表/详情的同一口径，作废巡视单不计入。"""
    return service.stats(month=month)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条巡视单明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"巡视单 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条巡视单，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="巡视单已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条巡视单执行派发巡视、提交结果、作废巡视；不允许的动作会被拦下并说明原因。

    提交结果时可在 values 里带巡视时长与问题明细，数字由服务端按明细一次性
    计算并冻结；重复提交或对已提交单再动作都会被拒绝。
    """
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出巡视检查清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "patrol", "total": total, "items": items}
