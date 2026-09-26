"""温感器管理业务规则：状态流转、字段校验、校准判定与筛选口径都收在这里。

校准相关的硬规则见 sensor_rules.py；本服务负责把规则套到台账数据上：
- 列表 / 详情 / 导出统一走 build_view，结论口径完全一致；
- reconcile_all 供规则上线时对既有传感器数据按新口径重新标一遍；
- 校准记录保存时的拦截（日期倒挂、精度不符）在 calibration 服务里调用同一套判定。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.services.sensor_rules import (
    STATUS_DISABLED,
    STATUS_DUE,
    STATUS_NORMAL,
    STATUS_OFFSET,
    evaluate_calibration,
)
from app.store import store

MODULE = "sensor"
CALIBRATION_MODULE = "calibration"
REQUIRED_FIELDS = ["传感器编号", "所属车辆", "传感器型号"]
STATUS_ORDER = ["正常", "数据偏移", "待校准", "已停用"]
ACTION_RULES = {"偏移预警": "数据偏移", "安排校准": "正常", "停用传感器": "已停用"}
NEGATIVE_ACTIONS = ["停用传感器", "偏移预警"]

# 台账展示的判定列（列表与详情同源）
VIEW_FIELDS = [
    "传感器编号", "所属车辆", "传感器型号", "精度等级",
    "校准日期", "下次校准日", "电池电量", "传感器状态",
]


class SensorService:
    # ---- 判定视图：列表与详情共用，结论必须一致 -----------------------------
    def build_view(self, entry: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
        """在台账原始行上叠加校准判定结论。任何展示出口都只允许走这里。"""
        verdict = evaluate_calibration(
            entry, store.rows(CALIBRATION_MODULE), today=today
        )
        view = dict(entry)
        view["status"] = self._status_of(entry, verdict)
        view["临期"] = verdict["due"]
        view["校准判定"] = verdict["conclusion"]
        view["距到期天数"] = verdict["days_left"]
        view["到期阈值"] = verdict["threshold_days"]
        view["精度不符"] = verdict["precision_mismatch"]
        view["电量不足"] = verdict["low_battery"]
        view["判定说明"] = verdict["reason"]
        return view

    @staticmethod
    def _status_of(entry: dict[str, Any], verdict: dict[str, Any]) -> str:
        """台账状态：停用人工优先，其次规则自动判待校准，其余保留人工状态。"""
        if verdict["disabled"]:
            return STATUS_DISABLED
        if verdict["due"]:
            return STATUS_DUE
        current = str(entry.get("status") or STATUS_NORMAL)
        return current if current in STATUS_ORDER else STATUS_NORMAL

    # ---- 查询 -------------------------------------------------------------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        views = [self.build_view(row) for row in store.rows(MODULE)]
        if keyword:
            views = [row for row in views if keyword in str(row.get("传感器编号", ""))]
        if status:
            views = [row for row in views if row.get("status") == status]
        total = len(views)
        start = max(page - 1, 0) * size
        return views[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        # 详情与台账同口径，避免两边结论打架
        return self.build_view(entry)

    def summary(self) -> list[dict[str, Any]]:
        """台账顶部统计卡片，数字全部来自同一套判定视图。"""
        views = [self.build_view(row) for row in store.rows(MODULE)]
        return [
            {"label": "在管传感器", "value": sum(1 for v in views if v["status"] != STATUS_DISABLED)},
            {"label": "待校准", "value": sum(1 for v in views if v["status"] == STATUS_DUE)},
            {"label": "精度不符", "value": sum(1 for v in views if v["精度不符"])},
            {"label": "低电量免判", "value": sum(1 for v in views if v["电量不足"] and not v["精度不符"] and v["status"] != STATUS_DISABLED)},
            {"label": "已停用", "value": sum(1 for v in views if v["status"] == STATUS_DISABLED)},
        ]

    # ---- 写入 -------------------------------------------------------------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], str]:
        """返回（视图, 缺失字段, 业务错误说明）；后两者同时只有一个非空。"""
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, ""
        rows = store.rows(MODULE)
        sensor_no = str(values["传感器编号"]).strip()
        if any(str(row.get("传感器编号") or "").strip() == sensor_no for row in rows):
            return None, [], f"传感器编号 {sensor_no} 已存在，请直接登记校准记录"
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in VIEW_FIELDS:
            if field != "传感器状态" and values.get(field) not in (None, ""):
                entry[field] = values[field]
        entry["传感器编号"] = sensor_no
        entry["status"] = STATUS_NORMAL
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self.build_view(entry), [], ""

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str, bool]:
        """返回（视图, 消息, 动作是否真正执行）；被规则拦截时 applied=False。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"温度传感器 {entry_id} 不存在或已归档", False
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于温感器管理可执行范围", False
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里", False

        # 精度不符且在用：拦截「安排校准」这种恢复使用的动作，不能假装恢复正常；
        # 必须先补一条精度合格的校准记录（经 calibration 服务校验），或停用传感器。
        # 「偏移预警」是负面上报、「停用传感器」是离场，二者仍允许。
        before_view = self.build_view(entry)
        if target == STATUS_NORMAL and before_view["精度不符"]:
            return before_view, (
                "该传感器精度等级不符所属车辆要求且仍在使用，"
                "请先保存精度合格的校准记录，或停用后再处理"
            ), False

        # 停用是终态；其余动作改完人工状态后仍要按规则重新判一遍，
        # 防止手动「安排校准」把临期传感器的待校准标记冲掉。
        # 注意：先改台账字段再 build_view，视图是拷贝，顺序反了会带出旧 pending。
        entry["status"] = target
        entry["pending"] = target != STATUS_DISABLED
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        view = self.build_view(entry)
        if target != STATUS_DISABLED and view["status"] == STATUS_DUE:
            return view, (
                f"温度传感器已{action}；该传感器距下次校准日仅剩 "
                f"{view['距到期天数']} 天，仍按规则判为待校准"
            ), True
        return view, f"温度传感器已{action}", True

    # ---- 规则上线：既有数据按新口径重新标一遍 -------------------------------
    def reconcile_all(self, *, today: date | None = None) -> dict[str, int]:
        """按新口径重刷全部存量传感器的台账状态与标记。

        - 校准记录里同编号多条的，以最近一次为准，回写台账校准/电量/精度字段；
        - 停用、低电量不参与到期判定，保留原状；
        - 临期（不足本车阈值）自动置为待校准，不再临期的恢复正常/数据偏移。
        幂等：重复执行结果一致。
        """
        today = today or date.today()
        records = store.rows(CALIBRATION_MODULE)
        changed = 0
        due_count = 0
        mismatch_count = 0
        for entry in store.rows(MODULE):
            sensor_no = str(entry.get("传感器编号") or "").strip()
            latest = self._latest_record(records, sensor_no)
            if latest is not None:
                for field in ("校准日期", "下次校准日", "电池电量", "精度等级"):
                    value = latest.get(field)
                    if value not in (None, ""):
                        entry[field] = value

            before = entry.get("status")
            verdict = evaluate_calibration(entry, records, today=today)
            if verdict["disabled"]:
                entry["status"] = STATUS_DISABLED
                entry["pending"] = False
            elif verdict["due"]:
                entry["status"] = STATUS_DUE
                entry["pending"] = True
                due_count += 1
            else:
                # 规则不再判待校准：保留人工的偏移预警，否则回到正常
                entry["status"] = (
                    STATUS_OFFSET if before == STATUS_OFFSET else STATUS_NORMAL
                )
                entry["pending"] = entry["status"] != STATUS_DISABLED
            entry["abnormal"] = entry["status"] == STATUS_OFFSET
            if verdict["precision_mismatch"]:
                mismatch_count += 1
            if entry["status"] != before:
                changed += 1
        return {"total": len(store.rows(MODULE)), "changed": changed,
                "due": due_count, "precision_mismatch": mismatch_count}

    @staticmethod
    def _latest_record(records: list[dict[str, Any]], sensor_no: str) -> dict[str, Any] | None:
        from app.services.sensor_rules import latest_calibration

        return latest_calibration(records, sensor_no)
