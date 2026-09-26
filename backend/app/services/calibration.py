"""校准记录业务规则。

保存一条校准记录时按顺序做硬校验，任何一条不过都不允许落库，并把原因讲清楚：
1. 必填字段缺失；
2. 校准日期晚于「下次校准日」——本次校准不可能发生在下次校准之后；
3. 精度等级不符所属车辆要求且传感器仍在使用（未停用、电量正常）——必须拦下。

保存成功后：
- 同一传感器编号出现多次时，台账以最近一次校准记录为准（sensor_service 统一处理）；
- 台账状态立刻按新口径重判，列表与详情结论随之变化。
"""
from __future__ import annotations

from typing import Any

from app.services.sensor import SensorService
from app.services.sensor_rules import (
    STATUS_DISABLED,
    parse_date,
    vehicle_rule,
    normalize_precision,
    precision_matches,
)
from app.store import store

MODULE = "calibration"
SENSOR_MODULE = "sensor"
REQUIRED_FIELDS = ["传感器编号", "校准日期", "下次校准日", "精度等级"]


class CalibrationService:
    def __init__(self) -> None:
        self.sensors = SensorService()

    def list_records(
        self,
        *,
        keyword: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(store.rows(MODULE))
        # 列表倒序展示，最近一次校准在最上面
        rows.sort(key=lambda row: (str(row.get("校准日期") or ""), int(row.get("id", 0))), reverse=True)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("传感器编号", ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def create_record(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        cleaned = {field: values.get(field) for field in REQUIRED_FIELDS}
        sensor_no = str(cleaned["传感器编号"] or "").strip()

        missing = [field for field in REQUIRED_FIELDS if not str(cleaned[field] or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"

        sensor = self._find_sensor(sensor_no)
        if sensor is None:
            return None, (
                f"传感器编号 {sensor_no} 在温感器台账中不存在，"
                "请先登记传感器再保存校准记录"
            )

        cal_date = parse_date(cleaned["校准日期"])
        next_date = parse_date(cleaned["下次校准日"])
        if cal_date is None:
            return None, f"校准日期「{cleaned['校准日期']}」格式无效，请使用 YYYY-MM-DD"
        if next_date is None:
            return None, f"下次校准日「{cleaned['下次校准日']}」格式无效，请使用 YYYY-MM-DD"

        # 硬规则：校准日期晚于下次校准日的数据不允许保存
        if cal_date > next_date:
            return None, (
                f"校准日期 {cal_date.isoformat()} 晚于下次校准日 "
                f"{next_date.isoformat()}，本次校准不可能发生在下次校准之后，"
                "请核对日期后重新填写"
            )

        # 硬规则：精度等级不符且仍在用（未停用）的必须拦下。
        # 与 evaluate_calibration 同口径：仅“已停用”豁免精度校验，低电量只豁免到期判定。
        actual = normalize_precision(cleaned["精度等级"])
        rule = vehicle_rule(sensor.get("所属车辆"))
        required = normalize_precision(rule.get("required_precision"))
        if str(sensor.get("status") or "") != STATUS_DISABLED and not precision_matches(actual, required):
            return None, (
                f"传感器 {sensor_no} 精度等级为 {actual or cleaned['精度等级']}，"
                f"所属车辆要求 {required} 级及以上且该传感器仍在使用，"
                "按规定不得保存该校准数据，请更换传感器或停用后再处理"
            )

        record = {
            "id": max((int(row.get("id", 0)) for row in store.rows(MODULE)), default=0) + 1,
            "校准编号": f"CALI-{max((int(row.get('id', 0)) for row in store.rows(MODULE)), default=0) + 1:04d}",
            "传感器编号": sensor_no,
            "所属车辆": sensor.get("所属车辆"),
            "校准日期": cal_date.isoformat(),
            "下次校准日": next_date.isoformat(),
            "精度等级": actual or str(cleaned["精度等级"]).strip(),
        }
        if str(values.get("电池电量") or "").strip():
            record["电池电量"] = str(values["电池电量"]).strip()
        store.rows(MODULE).append(record)

        # 同编号多次校准时以最近一次为准：立刻按新口径重刷该传感器台账
        self.sensors.reconcile_all()
        entry = store.find(SENSOR_MODULE, int(sensor["id"]))
        return self.sensors.build_view(entry), "校准记录已保存，传感器台账已按最新校准数据重新判定"

    @staticmethod
    def _find_sensor(sensor_no: str) -> dict[str, Any] | None:
        for row in store.rows(SENSOR_MODULE):
            if str(row.get("传感器编号") or "").strip() == sensor_no:
                return row
        return None
