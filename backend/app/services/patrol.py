"""巡视检查业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "patrol"
REQUIRED_FIELDS = ["巡视单号", "巡视路线", "巡视人员"]
STATUS_ORDER = ["待派发", "巡视中", "已提交", "已作废"]
ACTION_RULES = {"派发巡视": "巡视中", "提交结果": "已提交", "作废巡视": "已作废"}
NEGATIVE_ACTIONS = ["作废巡视"]

SUBMITTED_STATUS = "已提交"
VOID_STATUS = "已作废"
MAX_PATROL_HOURS = 8.0  # 单次巡视时长上限（小时），超出的在列表与统计里单独标出


def _read_count(value: Any) -> int | None:
    """读取数量字段：能解析成非负整数就返回，其余一律当作未填写。"""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _read_hours(value: Any) -> float | None:
    """读取巡视时长：能解析成非负小数就返回，其余一律当作未填写。"""
    try:
        hours = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return hours if hours >= 0 else None


def patrol_metrics(entry: dict[str, Any]) -> dict[str, Any]:
    """单张巡视单的统一口径：发现问题数、整改项数、巡视时长与超时标记。

    列表、详情、导出与统计全部从这里取数，页面不再自行计算；
    整改项数不会多于发现问题数，超过时长上限的单独标出。
    """
    found = _read_count(entry.get("发现问题数")) or 0
    fixed = _read_count(entry.get("整改项数")) or 0
    hours = _read_hours(entry.get("巡视时长"))
    return {
        "发现问题数": found,
        "整改项数": min(fixed, found),
        "巡视时长": hours,
        "超时标记": "超时" if hours is not None and hours > MAX_PATROL_HOURS else "—",
    }


def patrol_row(entry: dict[str, Any]) -> dict[str, Any]:
    """对外输出的一张巡视单：原始字段叠加统一口径，保证各端看到的是同一份结果。"""
    row = dict(entry)
    row.update(patrol_metrics(entry))
    row["巡视状态"] = entry.get("status")
    return row


def _submit_count(values: dict[str, Any], entry: dict[str, Any], field: str) -> int:
    """提交结果时校验数量字段：留空则沿用单上已有值，显式填写就必须是非负整数。"""
    raw = values.get(field)
    if raw is None or str(raw).strip() == "":
        return _read_count(entry.get(field)) or 0
    number = _read_count(raw)
    if number is None:
        raise ValueError(f"{field}需要是非负整数，当前值「{raw}」无法入账")
    return number


def _submit_hours(values: dict[str, Any], entry: dict[str, Any]) -> float | None:
    """提交结果时校验巡视时长：留空则沿用单上已有值，显式填写就必须是非负小数。"""
    raw = values.get("巡视时长")
    if raw is None or str(raw).strip() == "":
        return _read_hours(entry.get("巡视时长"))
    hours = _read_hours(raw)
    if hours is None:
        raise ValueError(f"巡视时长需要是非负数字，当前值「{raw}」无法入账")
    return hours


class PatrolService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("巡视单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [patrol_row(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return patrol_row(entry) if entry is not None else None

    def stats(self) -> list[dict[str, Any]]:
        """巡视检查统计口径：作废单不参与合计，数量与超时都取自 patrol_metrics。"""
        rows = [row for row in store.rows(MODULE) if row.get("status") != VOID_STATUS]
        month = date.today().strftime("%Y-%m")
        month_rows = [row for row in rows if str(row.get("巡视日期") or "").startswith(month)]
        found_total = sum(patrol_metrics(row)["发现问题数"] for row in month_rows)
        fixed_total = sum(patrol_metrics(row)["整改项数"] for row in month_rows)
        overtime = sum(1 for row in rows if patrol_metrics(row)["超时标记"] == "超时")
        return [
            {"label": "待派发巡视", "value": sum(1 for row in rows if row.get("status") == "待派发")},
            {"label": "巡视中任务", "value": sum(1 for row in rows if row.get("status") == "巡视中")},
            {"label": "本月发现问题", "value": found_total},
            {"label": "本月整改项", "value": fixed_total},
            {"label": "超时巡视单", "value": overtime},
        ]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return patrol_row(entry), []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"巡视单 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于巡视检查可执行范围"
        if action == "提交结果":
            return self._submit_result(entry, values or {})
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return patrol_row(entry), f"巡视单已{action}"

    def _submit_result(
        self,
        entry: dict[str, Any],
        values: dict[str, Any],
    ) -> tuple[dict[str, Any] | None, str]:
        """提交巡视结果：数量校验通过后落账并锁定，重复提交只保留首次结果。"""
        if entry.get("结果锁定"):
            return patrol_row(entry), "巡视单已提交过，结果以首次提交为准，本次不重复记录"
        if entry.get("status") == VOID_STATUS:
            return None, "巡视单已作废，不能再提交结果"
        try:
            found = _submit_count(values, entry, "发现问题数")
            fixed = _submit_count(values, entry, "整改项数")
            hours = _submit_hours(values, entry)
        except ValueError as exc:
            return None, str(exc)
        if fixed > found:
            return None, f"整改项数 {fixed} 不能多于发现问题数 {found}，请核对后再提交"
        entry["发现问题数"] = found
        entry["整改项数"] = fixed
        entry["巡视时长"] = hours
        entry["status"] = SUBMITTED_STATUS
        entry["pending"] = False
        entry["abnormal"] = False
        entry["结果锁定"] = True
        return patrol_row(entry), "巡视单已提交结果，数量已锁定"
