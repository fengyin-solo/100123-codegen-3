"""温感器管理业务规则：校准判定、字段校验与筛选口径都收在这里。

校准口径（2026-09 起执行）：
1. 下次校准日距今天不足阈值的传感器自动标为「待校准」，阈值按所属车辆区分，
   未单独配置的车辆走默认 30 天；
2. 校准日期晚于下次校准日的数据不允许保存，保存时说明原因；
3. 精度等级不符且仍在用的传感器一律拦下：不允许登记、不允许执行在用动作，只能停用；
4. 电量不足（低于 20%）与已停用的传感器不参与到期判定；
5. 同一传感器编号出现多条校准记录时，以校准日期最近的一条为准。

规则只升不降：到期自动标「待校准」，但不会自动把「待校准」改回「正常」，
要回到正常只能登记一条新的校准记录（以最近一次为准）或执行动作。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "sensor"
REQUIRED_FIELDS = ["传感器编号", "所属车辆", "传感器型号"]
ENTRY_FIELDS = ["传感器编号", "所属车辆", "传感器型号", "精度等级", "校准日期", "下次校准日", "电池电量"]
STATUS_ORDER = ["正常", "数据偏移", "待校准", "已停用"]
ACTION_RULES = {"偏移预警": "数据偏移", "安排校准": "待校准", "停用传感器": "已停用"}
NEGATIVE_ACTIONS = ["停用传感器"]

STATUS_NORMAL, STATUS_DRIFT, STATUS_DUE, STATUS_RETIRED = STATUS_ORDER

DEFAULT_DUE_DAYS = 30  # 默认口径：下次校准日距今不足 30 天即自动标待校准
VEHICLE_DUE_DAYS = {  # 阈值按所属车辆区分；未配置的车辆走默认口径
    "FLEE-0001": 45,
    "FLEE-0002": 30,
    "FLEE-0003": 15,
}
LOW_BATTERY_PERCENT = 20.0  # 电量低于该值视为电量不足，不参与到期判定
ALLOWED_PRECISION_LEVELS = ("A级", "B级")  # 允许在用的精度等级，其余一律拦下


def _parse_date(value: Any) -> date | None:
    """把「2026-09-01」这类字符串解析成日期；解析不了返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_battery(value: Any) -> float | None:
    """电量兼容「85%」「85」两种写法，返回百分数；解析不了返回 None。"""
    text = str(value or "").strip().rstrip("%").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _due_threshold(vehicle: Any) -> int:
    """校准到期阈值按所属车辆区分，未配置的车辆用默认口径。"""
    return VEHICLE_DUE_DAYS.get(str(vehicle or "").strip(), DEFAULT_DUE_DAYS)


def _build_context(rows: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """汇总判定上下文：同一传感器编号出现多条校准记录时，以校准日期最近的一条为准。"""
    latest: dict[str, tuple[date, int]] = {}
    for row in rows:
        code = str(row.get("传感器编号") or "").strip()
        if not code:
            continue
        marker = (_parse_date(row.get("校准日期")) or date.min, int(row.get("id", 0)))
        if code not in latest or marker > latest[code]:
            latest[code] = marker
    return {"today": today, "latest_ids": {code: marker[1] for code, marker in latest.items()}}


def _apply_rules(entry: dict[str, Any], ctx: dict[str, Any]) -> None:
    """按校准口径刷新单条记录的就绪状态与结论。

    台账、详情、汇总、导出都走这一个入口，保证各处结论一致。
    """
    today: date = ctx["today"]
    code = str(entry.get("传感器编号") or "").strip()
    entry["精度拦截"] = False
    entry["传感器状态"] = str(entry.get("status") or STATUS_NORMAL)

    # 同一编号以最近一次校准记录为准，旧记录不参与判定
    if code and ctx["latest_ids"].get(code) not in (None, entry.get("id")):
        entry["校准结论"] = "同一传感器编号存在更新的校准记录，以最近一次为准，本条不参与判定"
        return

    if entry.get("status") == STATUS_RETIRED:
        entry["pending"] = False
        entry["校准结论"] = "已停用，不参与校准到期判定"
        return

    level = str(entry.get("精度等级") or "").strip()
    if level not in ALLOWED_PRECISION_LEVELS:
        entry["abnormal"] = True
        entry["精度拦截"] = True
        allowed = "、".join(ALLOWED_PRECISION_LEVELS)
        entry["校准结论"] = f"精度等级「{level or '未填写'}」不符在用要求（允许 {allowed}），传感器必须停用"
        return

    battery = _parse_battery(entry.get("电池电量"))
    if battery is not None and battery < LOW_BATTERY_PERCENT:
        entry["校准结论"] = f"电量不足（{battery:g}%），不参与校准到期判定"
        return

    next_date = _parse_date(entry.get("下次校准日"))
    if next_date is None:
        entry["校准结论"] = "下次校准日缺失或格式不正确，无法判定，请补录"
        return

    threshold = _due_threshold(entry.get("所属车辆"))
    days_left = (next_date - today).days
    if days_left < threshold:
        entry["status"] = STATUS_DUE
        entry["pending"] = True
        entry["传感器状态"] = STATUS_DUE
        if days_left < 0:
            entry["校准结论"] = f"已超过下次校准日 {-days_left} 天（阈值 {threshold} 天），自动标为待校准"
        else:
            entry["校准结论"] = f"距下次校准日还有 {days_left} 天，不足 {threshold} 天阈值，自动标为待校准"
    else:
        entry["校准结论"] = f"校准有效，距下次校准日还有 {days_left} 天（阈值 {threshold} 天）"


def _validate_values(values: dict[str, Any]) -> list[str]:
    """保存前校验：返回问题清单，空清单表示可以保存。"""
    errors: list[str] = []
    missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
    if missing:
        errors.append(f"缺少必填字段：{'、'.join(missing)}")

    calibrated = _parse_date(values.get("校准日期"))
    next_date = _parse_date(values.get("下次校准日"))
    if str(values.get("校准日期") or "").strip() and calibrated is None:
        errors.append("校准日期格式不正确，应为 YYYY-MM-DD")
    if str(values.get("下次校准日") or "").strip() and next_date is None:
        errors.append("下次校准日格式不正确，应为 YYYY-MM-DD")
    if calibrated and next_date and calibrated > next_date:
        errors.append(
            f"校准日期（{calibrated.isoformat()}）晚于下次校准日（{next_date.isoformat()}），数据不允许保存"
        )

    level = str(values.get("精度等级") or "").strip()
    if level not in ALLOWED_PRECISION_LEVELS:
        allowed = "、".join(ALLOWED_PRECISION_LEVELS)
        errors.append(f"精度等级「{level or '未填写'}」不符在用要求（允许 {allowed}），传感器不允许登记为在用")
    return errors


class SensorService:
    def __init__(self) -> None:
        # 规则上线即按新口径把既有传感器数据重新标一遍
        self.relabel_all()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        ctx = _build_context(rows, date.today())
        for row in rows:
            _apply_rules(row, ctx)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("传感器编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is not None:
            ctx = _build_context(store.rows(MODULE), date.today())
            _apply_rules(entry, ctx)
        return entry

    def summary(self) -> dict[str, Any]:
        """校准口径汇总：各状态数量与精度拦截数量，给台账看板用。"""
        rows = store.rows(MODULE)
        ctx = _build_context(rows, date.today())
        counts = {status: 0 for status in STATUS_ORDER}
        blocked = 0
        for row in rows:
            _apply_rules(row, ctx)
            counts[str(row.get("status"))] = counts.get(str(row.get("status")), 0) + 1
            if row.get("精度拦截"):
                blocked += 1
        return {"total": len(rows), "status_counts": counts, "精度拦截": blocked}

    def relabel_all(self, *, today: date | None = None) -> int:
        """把既有传感器数据按新口径重新标一遍，返回状态发生变化的条数。"""
        rows = store.rows(MODULE)
        ctx = _build_context(rows, today or date.today())
        changed = 0
        for row in rows:
            before = (row.get("status"), row.get("pending"), row.get("abnormal"))
            _apply_rules(row, ctx)
            if (row.get("status"), row.get("pending"), row.get("abnormal")) != before:
                changed += 1
        return changed

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        errors = _validate_values(values)
        if errors:
            return None, errors
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: str(values.get(field) or "").strip() for field in ENTRY_FIELDS})
        entry["status"] = STATUS_NORMAL
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        ctx = _build_context(rows, date.today())
        _apply_rules(entry, ctx)
        entry["传感器状态"] = str(entry["status"])
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"温度传感器 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于温感器管理可执行范围"
        level = str(entry.get("精度等级") or "").strip()
        if entry.get("status") != STATUS_RETIRED and level not in ALLOWED_PRECISION_LEVELS and action != "停用传感器":
            return None, f"精度等级「{level or '未填写'}」不符在用要求，传感器必须停用，不能执行「{action}」"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        ctx = _build_context(store.rows(MODULE), date.today())
        _apply_rules(entry, ctx)
        entry["传感器状态"] = str(entry["status"])
        return entry, f"温度传感器已执行「{action}」，当前状态：{entry['status']}"
