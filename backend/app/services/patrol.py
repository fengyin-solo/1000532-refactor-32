"""巡视检查业务规则：状态流转、字段校验与问题/整改口径都收在这里。

发现问题数与整改项数只允许在本模块按「问题明细」计算一次，列表、详情与
统计统一走 ``_decorate_entry`` 的结果，页面与接口不再各写一份口径。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "patrol"
REQUIRED_FIELDS = ["巡视单号", "巡视路线", "巡视人员"]
STATUS_ORDER = ["待派发", "巡视中", "已提交", "已作废"]
ACTION_RULES = {"派发巡视": "巡视中", "提交结果": "已提交", "作废巡视": "已作废"}
NEGATIVE_ACTIONS = ["作废巡视"]
SUBMITTED = "已提交"
VOIDED = "已作废"
# 巡视时长上限（分钟），超过即在列表与统计里单独标出
MAX_DURATION_MINUTES = 240


def _counts(entry: dict[str, Any]) -> tuple[int, int]:
    """巡视单「发现问题数 / 整改项数」的唯一计算口径。

    每条问题明细记一个发现问题，其下整改项逐条计数；因此整改项数
    可能大于或小于发现问题数，一切以提交时冻结的明细为准。
    """
    problems = entry.get("问题明细") or []
    problem_count = len(problems)
    rectify_count = sum(len(problem.get("整改项") or []) for problem in problems)
    return problem_count, rectify_count


def _decorate_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """在不动原始记录的前提下，补出统一口径的派生字段供列表与详情共用。"""
    problem_count, rectify_count = _counts(entry)
    duration = int(entry.get("巡视时长") or 0)
    view = dict(entry)
    view["发现问题数"] = problem_count
    view["整改项数"] = rectify_count
    view["巡视时长"] = duration
    view["巡视状态"] = entry.get("status")
    view["超时"] = entry.get("status") == SUBMITTED and duration > MAX_DURATION_MINUTES
    return view


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
        return [_decorate_entry(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return _decorate_entry(entry) if entry is not None else None

    def stats(self, month: str | None = None) -> dict[str, Any]:
        """巡视合计口径：作废巡视单不参与任何合计。"""
        month = month or date.today().strftime("%Y-%m")
        rows = [row for row in store.rows(MODULE) if row.get("status") != VOIDED]
        cards = [
            {"label": "待派发巡视", "value": 0},
            {"label": "巡视中任务", "value": 0},
            {"label": "本月发现问题", "value": 0},
            {"label": "本月整改项", "value": 0},
            {"label": "超时巡视", "value": 0},
        ]
        values = {card["label"]: card["value"] for card in cards}
        values["待派发巡视"] = sum(1 for row in rows if row.get("status") == "待派发")
        values["巡视中任务"] = sum(1 for row in rows if row.get("status") == "巡视中")
        for row in rows:
            view = _decorate_entry(row)
            if str(row.get("巡视日期") or "").startswith(month):
                values["本月发现问题"] += int(view["发现问题数"])
                values["本月整改项"] += int(view["整改项数"])
            if view["超时"]:
                values["超时巡视"] += 1
        for card in cards:
            card["value"] = values[card["label"]]
        return {"month": month, "cards": cards}

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["巡视日期"] = str(values.get("巡视日期") or "").strip()
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        # 结果数据在「提交结果」时才落账，登记时一律为空
        entry["巡视时长"] = 0
        entry["问题明细"] = []
        rows.append(entry)
        return _decorate_entry(entry), []

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
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        status = entry.get("status")
        if action == "派发巡视":
            if status != "待派发":
                return None, f"巡视单当前为{status}状态，不能派发巡视"
        elif action == "提交结果":
            if status == SUBMITTED:
                # 重复提交只认第一次：数字已冻结，原样返回不覆盖
                return None, "巡视结果已提交，不能重复提交，问题数以首次提交为准"
            if status == VOIDED:
                return None, "巡视单已作废，不能再提交结果"
            if status != "巡视中":
                return None, f"巡视单当前为{status}状态，需先派发巡视再提交结果"
            message = self._apply_result(entry, values or {})
            if message:
                return None, message
        elif action == "作废巡视":
            if status == SUBMITTED:
                return None, "巡视结果已提交且数字已锁定，不能作废"
            if status == VOIDED:
                return None, "巡视单已作废，无需重复作废"

        entry["status"] = target
        entry["pending"] = target == "巡视中"
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return _decorate_entry(entry), f"巡视单已{action}"

    def _apply_result(self, entry: dict[str, Any], values: dict[str, Any]) -> str | None:
        """提交结果时一次性落账并冻结：巡视时长与问题明细之后不再允许改动。"""
        duration = values.get("巡视时长", 0)
        try:
            duration = int(float(duration))
        except (TypeError, ValueError):
            return "巡视时长需要填写为不小于 0 的分钟数"
        if duration < 0:
            return "巡视时长不能为负数"

        raw_problems = values.get("问题明细", [])
        if not isinstance(raw_problems, list):
            return "问题明细需要按问题列表提交"
        problems: list[dict[str, Any]] = []
        for item in raw_problems:
            if not isinstance(item, dict):
                return "每条问题明细需要包含问题描述与整改项"
            raw_rectifies = item.get("整改项") or []
            if not isinstance(raw_rectifies, list):
                return "整改项需要按列表提交"
            problems.append({
                "问题": str(item.get("问题") or item.get("问题描述") or "").strip(),
                "整改项": [str(text).strip() for text in raw_rectifies if str(text).strip()],
            })

        entry["巡视时长"] = duration
        entry["问题明细"] = problems
        return None
