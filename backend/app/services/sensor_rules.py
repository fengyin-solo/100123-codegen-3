"""温感器校准判定规则。

口径说明（业务方确认版）：
1. 下次校准日距今天不足阈值（默认 30 天，按所属车辆区分）的传感器，自动判为「待校准」；
2. 已停用、电量不足的传感器不参与到期判定，即使临期也不自动标记；
3. 传感器实际精度等级不满足所属车辆要求且仍在用的，判为「精度不符」并拦截使用；
4. 同一个传感器编号在校准记录里出现多次时，以最近一次（校准日期最新）为准；
5. 台账列表与传感器详情共用 evaluate_calibration 一个出口，结论必须一致。

本模块只做纯判定、不读写 store，方便单测固定“今天”。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

# 默认到期阈值（天）：距下次校准日不足该天数即待校准
DEFAULT_DUE_DAYS = 30
# 电量不足阈值：剩余电量低于该百分比的传感器不参与到期判定
LOW_BATTERY_PERCENT = 20
# 精度等级由高到低：A 级可兼容 B、C 级要求，反之不行
PRECISION_ORDER = ["A", "B", "C"]
STATUS_DISABLED = "已停用"
STATUS_OFFSET = "数据偏移"
STATUS_DUE = "待校准"
STATUS_NORMAL = "正常"

# 按所属车辆区分的阈值与精度要求；未配置的车辆走默认阈值。
# key 支持按「所属车辆」完整值匹配，也支持车牌关键字包含匹配（如 京A）。
VEHICLE_RULES: list[dict[str, Any]] = [
    {"match": "京A", "due_days": 45, "required_precision": "A"},
    {"match": "沪B-冷链车2", "due_days": 15, "required_precision": "B"},
    {"match": "粤C", "due_days": 30, "required_precision": "C"},
]


def parse_date(value: Any) -> date | None:
    """尽量宽松地解析日期；解析不了返回 None（缺日期不能当作临期处理）。"""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_battery(value: Any) -> int | None:
    """把电池电量解析成百分比整数。

    兼容三种存量写法：85（整数百分比）、"85%"、0.85（小数比例）。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if 0 < number <= 1:
            number *= 100
        return int(round(number))
    text = str(value).strip().rstrip("%")
    try:
        number = float(text)
    except ValueError:
        return None
    if 0 < number <= 1:
        number *= 100
    return int(round(number))


def normalize_precision(value: Any) -> str | None:
    """归一化精度等级：a / A级 / A 等都识别为 A；识别不了返回 None。"""
    if value is None:
        return None
    text = str(value).strip().upper().rstrip("级").strip()
    if text in PRECISION_ORDER:
        return text
    # 兼容「一级/二级/三级」这类写法：一级最好
    cn_map = {"一": "A", "二": "B", "三": "C", "1": "A", "2": "B", "3": "C"}
    return cn_map.get(text)


def vehicle_rule(vehicle: Any) -> dict[str, Any]:
    """取所属车辆对应的阈值配置：精确匹配优先，其次关键字包含匹配。"""
    name = str(vehicle or "").strip()
    fallback = {"match": None, "due_days": DEFAULT_DUE_DAYS, "required_precision": None}
    if not name:
        return fallback
    for rule in VEHICLE_RULES:
        if name == rule["match"]:
            return rule
    for rule in VEHICLE_RULES:
        if rule["match"] and rule["match"] in name:
            return rule
    return fallback


def latest_calibration(records: list[dict[str, Any]], sensor_no: str) -> dict[str, Any] | None:
    """同一传感器编号在校准记录里出现多次时，以最近一次校准日期为准。

    日期缺失或无法解析的记录排到最后；全都没有日期时取列表里最后一条，
    与“最近一次录入”的直觉保持一致。
    """
    matched = [r for r in records if str(r.get("传感器编号") or "").strip() == sensor_no]
    if not matched:
        return None

    def sort_key(row: dict[str, Any]) -> tuple[int, str]:
        parsed = parse_date(row.get("校准日期"))
        return (1, parsed.isoformat()) if parsed else (0, "")

    return max(enumerate(matched), key=lambda item: (sort_key(item[1]), item[0]))[1]


def precision_matches(actual: str | None, required: str | None) -> bool:
    """实际精度是否满足车辆要求：等级在 PRECISION_ORDER 中越靠前越高。"""
    if not required:
        return True
    if not actual:
        return False
    if actual not in PRECISION_ORDER or required not in PRECISION_ORDER:
        return actual == required
    return PRECISION_ORDER.index(actual) <= PRECISION_ORDER.index(required)


def evaluate_calibration(
    sensor: dict[str, Any],
    calibration_records: list[dict[str, Any]] | None = None,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """对单只传感器给出校准判定结论。台账与详情共用此函数。

    返回字段：
    - conclusion：待校准 / 精度不符 / 已停用 / 低电量免判 / 正常 / 无校准计划
    - due：是否按规则自动判为待校准
    - precision_mismatch：精度等级不符且仍在用
    - days_left：距下次校准日天数（负数表示已过期）；无日期为 None
    - threshold_days：本车适用的到期阈值
    - reason：人话说明，前端直接展示
    """
    today = today or date.today()
    records = calibration_records or []
    sensor_no = str(sensor.get("传感器编号") or "").strip()
    latest = latest_calibration(records, sensor_no)

    # 台账字段为准，校准记录里的最近一次覆盖台账（字段不全时回退台账）
    def pick(field: str) -> Any:
        if latest is not None and str(latest.get(field) or "").strip() != "":
            return latest[field]
        return sensor.get(field)

    vehicle = sensor.get("所属车辆")
    rule = vehicle_rule(vehicle)
    threshold = int(rule["due_days"])
    required = normalize_precision(rule.get("required_precision"))
    actual = normalize_precision(pick("精度等级"))
    battery = parse_battery(pick("电池电量"))
    next_date = parse_date(pick("下次校准日"))
    days_left = (next_date - today).days if next_date else None
    current_status = str(sensor.get("status") or "")

    disabled = current_status == STATUS_DISABLED
    low_battery = battery is not None and battery < LOW_BATTERY_PERCENT
    mismatch = (not disabled) and (not precision_matches(actual, required))

    result: dict[str, Any] = {
        "sensor_no": sensor_no,
        "vehicle": str(vehicle or ""),
        "threshold_days": threshold,
        "required_precision": required,
        "actual_precision": actual,
        "battery": battery,
        "next_calibration_date": next_date.isoformat() if next_date else None,
        "days_left": days_left,
        "low_battery": low_battery,
        "disabled": disabled,
        "precision_mismatch": mismatch,
        "due": False,
        "conclusion": STATUS_NORMAL,
        "reason": "",
        "latest_record_id": latest.get("校准编号") if latest else None,
    }

    if disabled:
        result["conclusion"] = STATUS_DISABLED
        result["reason"] = "传感器已停用，不参与校准到期判定"
        return result

    if mismatch:
        result["conclusion"] = "精度不符"
        result["reason"] = (
            f"精度等级 {actual or '缺失'} 不满足所属车辆要求的 {required} 级，"
            "该传感器不得继续使用，请更换或重新校准"
        )
        return result

    # 到期判定：已停用与电量不足的传感器不参与
    if low_battery:
        result["conclusion"] = "低电量免判"
        result["reason"] = (
            f"电池电量仅 {battery}%（低于 {LOW_BATTERY_PERCENT}%），"
            "不参与校准到期判定，请先更换电池"
        )
        return result

    if days_left is None:
        result["conclusion"] = "无校准计划"
        result["reason"] = "缺少下次校准日，无法判定校准到期情况，请补录校准记录"
        return result

    if days_left < 0:
        result["due"] = True
        result["conclusion"] = STATUS_DUE
        result["reason"] = f"校准已于 {abs(days_left)} 天前过期，请立即安排校准"
    elif days_left < threshold:
        result["due"] = True
        result["conclusion"] = STATUS_DUE
        result["reason"] = (
            f"距下次校准日仅剩 {days_left} 天（所属车辆阈值 {threshold} 天），请尽快安排校准"
        )
    else:
        result["conclusion"] = STATUS_NORMAL
        result["reason"] = f"校准有效，距下次校准日还有 {days_left} 天（阈值 {threshold} 天）"
    return result
