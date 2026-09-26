"""温感器校准判定规则测试：到期自动标记、保存校验、精度拦截、车辆阈值、
排除条件、重复记录去重、上线重标与台账/详情一致性。

用例里的日期都相对今天构造，保证任何一天跑都成立；
固定口径（2026-09-26）的一组用例直接验种子数据。
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.seed import SEED_ROWS
from app.services.sensor import (
    DEFAULT_DUE_DAYS,
    STATUS_DUE,
    STATUS_NORMAL,
    STATUS_RETIRED,
    SensorService,
)
from app.store import store

MODULE = "sensor"


def install(rows: list[dict]) -> None:
    """用给定记录替换内存台账（深拷贝，避免污染种子）。"""
    store._tables[MODULE] = [dict(row) for row in rows]


def make_row(
    row_id: int,
    *,
    code: str = "SENS-X",
    vehicle: str = "FLEE-0002",
    level: str = "A级",
    calibrated: str | None = "2026-01-01",
    next_cal: str | None = None,
    battery: str = "90%",
    status: str = STATUS_NORMAL,
) -> dict:
    today = date.today()
    return {
        "id": row_id,
        "status": status,
        "pending": True,
        "abnormal": False,
        "传感器编号": code,
        "所属车辆": vehicle,
        "传感器型号": "PT100-PRO",
        "精度等级": level,
        "校准日期": calibrated,
        "下次校准日": next_cal or (today + timedelta(days=90)).isoformat(),
        "电池电量": battery,
        "传感器状态": status,
    }


@pytest.fixture(autouse=True)
def fresh_service():
    install(SEED_ROWS[MODULE])
    return SensorService()


def iso(offset_days: int) -> str:
    return (date.today() + timedelta(days=offset_days)).isoformat()


# 1. 下次校准日距今不足阈值 → 自动标待校准 ---------------------------------

def test_due_soon_auto_marked(fresh_service):
    install([make_row(1, next_cal=iso(10))])
    changed = fresh_service.relabel_all()
    row = store.find(MODULE, 1)
    assert row["status"] == STATUS_DUE
    assert "待校准" in row["校准结论"]
    assert changed == 1


def test_threshold_boundary_is_strictly_less_than():
    # 恰好等于阈值不算「不足」，差一天才算
    install([
        make_row(1, code="SENS-A", next_cal=iso(DEFAULT_DUE_DAYS)),
        make_row(2, code="SENS-B", next_cal=iso(DEFAULT_DUE_DAYS - 1)),
    ])
    SensorService().relabel_all()
    assert store.find(MODULE, 1)["status"] == STATUS_NORMAL
    assert store.find(MODULE, 2)["status"] == STATUS_DUE


def test_overdue_marked():
    install([make_row(1, next_cal=iso(-3))])
    SensorService().relabel_all()
    row = store.find(MODULE, 1)
    assert row["status"] == STATUS_DUE
    assert "超过下次校准日 3 天" in row["校准结论"]


def test_far_enough_stays_normal():
    install([make_row(1, next_cal=iso(120))])
    SensorService().relabel_all()
    assert store.find(MODULE, 1)["status"] == STATUS_NORMAL
    assert "校准有效" in store.find(MODULE, 1)["校准结论"]


# 2. 阈值按所属车辆区分 -----------------------------------------------------

def test_threshold_differs_by_vehicle():
    # 同样剩 24 天：FLEE-0002 阈值 30 天 → 待校准；FLEE-0003 阈值 15 天 → 正常
    install([
        make_row(1, code="SENS-A", vehicle="FLEE-0002", next_cal=iso(24)),
        make_row(2, code="SENS-B", vehicle="FLEE-0003", next_cal=iso(24)),
    ])
    SensorService().relabel_all()
    assert store.find(MODULE, 1)["status"] == STATUS_DUE
    assert store.find(MODULE, 2)["status"] == STATUS_NORMAL


def test_unknown_vehicle_uses_default_threshold():
    install([make_row(1, vehicle="沪A-未配置车辆", next_cal=iso(DEFAULT_DUE_DAYS + 5))])
    SensorService().relabel_all()
    assert store.find(MODULE, 1)["status"] == STATUS_NORMAL


# 3. 电量不足与已停用不参与到期判定 -----------------------------------------

def test_low_battery_excluded_from_due():
    install([make_row(1, battery="12%", next_cal=iso(5))])
    SensorService().relabel_all()
    row = store.find(MODULE, 1)
    assert row["status"] == STATUS_NORMAL
    assert "电量不足" in row["校准结论"]


def test_retired_excluded_from_due():
    install([make_row(1, status=STATUS_RETIRED, next_cal=iso(5))])
    SensorService().relabel_all()
    row = store.find(MODULE, 1)
    assert row["status"] == STATUS_RETIRED
    assert "已停用" in row["校准结论"]


# 4. 精度等级不符还在用必须拦下 ---------------------------------------------

def test_bad_precision_flagged_and_blocked():
    install([make_row(1, level="C级")])
    service = SensorService()
    row = store.find(MODULE, 1)
    assert row["精度拦截"] is True
    assert row["abnormal"] is True
    assert "精度等级" in row["校准结论"]
    # 在用动作一律拦下
    for action in ("偏移预警", "安排校准"):
        entry, message = service.run_action(1, action)
        assert entry is None and "必须停用" in message
    # 停用是放行的
    entry, _ = service.run_action(1, "停用传感器")
    assert entry is not None and entry["status"] == STATUS_RETIRED


def test_valid_precision_not_blocked():
    install([make_row(1, level="B级", next_cal=iso(200))])
    service = SensorService()
    entry, _ = service.run_action(1, "偏移预警")
    assert entry is not None


# 5. 校准日期晚于下次校准日不允许保存 ---------------------------------------

def test_calibrated_after_next_rejected_on_save():
    service = SensorService()
    entry, errors = service.create_entry({
        "传感器编号": "SENS-NEW",
        "所属车辆": "FLEE-0002",
        "传感器型号": "PT100-PRO",
        "精度等级": "A级",
        "校准日期": iso(40),
        "下次校准日": iso(10),
        "电池电量": "80%",
    })
    assert entry is None
    assert errors and "不允许保存" in errors[0]
    assert iso(40) in errors[0] and iso(10) in errors[0]


def test_bad_precision_rejected_on_save():
    service = SensorService()
    entry, errors = service.create_entry({
        "传感器编号": "SENS-NEW",
        "所属车辆": "FLEE-0002",
        "传感器型号": "PT100-PRO",
        "精度等级": "C级",
        "校准日期": iso(-30),
        "下次校准日": iso(330),
        "电池电量": "80%",
    })
    assert entry is None
    assert errors and "不允许登记为在用" in errors[0]


def test_valid_save_applies_rules():
    service = SensorService()
    entry, errors = service.create_entry({
        "传感器编号": "SENS-NEW",
        "所属车辆": "FLEE-0002",
        "传感器型号": "PT100-PRO",
        "精度等级": "A级",
        "校准日期": iso(-30),
        "下次校准日": iso(10),
        "电池电量": "80%",
    })
    assert not errors
    assert entry["status"] == STATUS_DUE  # 保存成功即按新口径出结论


# 6. 同一编号两条记录以最近一次为准 -----------------------------------------

def test_duplicate_sensor_latest_record_wins():
    # 故意把较新校准日期放在较小 id 上，确认是按日期而非插入顺序取最近
    install([
        make_row(1, code="SENS-DUP", calibrated=iso(-55), next_cal=iso(310)),
        make_row(2, code="SENS-DUP", calibrated=iso(-300), next_cal=iso(-100)),
    ])
    SensorService().relabel_all()
    newer = store.find(MODULE, 1)
    older = store.find(MODULE, 2)
    assert newer["校准结论"].startswith("校准有效")
    assert "以最近一次为准" in older["校准结论"]
    assert older["status"] == STATUS_NORMAL  # 旧记录虽已过期但不参与判定


# 7. 规则上线：既有数据重标（固定 2026-09-26 口径验种子） --------------------

def test_seed_data_relabeled_at_go_live(fresh_service):
    install(SEED_ROWS[MODULE])  # 恢复成未重标的原始台账，模拟规则刚上线
    changed = fresh_service.relabel_all(today=date(2026, 9, 26))
    # SENS-0002 剩 14 天 < 30 天 → 正常变待校准
    assert store.find(MODULE, 2)["status"] == STATUS_DUE
    assert changed >= 1
    # SENS-0001（66 天/45 阈值）、SENS-0003（24 天/15 阈值）、SENS-0004（低电量）→ 仍正常
    assert store.find(MODULE, 1)["status"] == STATUS_NORMAL
    assert store.find(MODULE, 3)["status"] == STATUS_NORMAL
    assert store.find(MODULE, 4)["status"] == STATUS_NORMAL
    # SENS-0005 已停用不参与
    assert store.find(MODULE, 5)["status"] == STATUS_RETIRED
    # SENS-0006 C 级仍在用 → 拦截
    assert store.find(MODULE, 6)["精度拦截"] is True
    # SENS-0007 旧记录（id 7）被最近一次（id 8）覆盖
    assert "以最近一次为准" in store.find(MODULE, 7)["校准结论"]
    assert store.find(MODULE, 8)["校准结论"].startswith("校准有效")


def test_relabel_is_idempotent():
    install(SEED_ROWS[MODULE])
    service = SensorService()
    service.relabel_all(today=date(2026, 9, 26))
    assert service.relabel_all(today=date(2026, 9, 26)) == 0


# 8. 台账与详情结论一致 ------------------------------------------------------

def test_list_and_detail_conclusions_consistent():
    install(SEED_ROWS[MODULE])
    service = SensorService()
    items, total = service.list_entries()
    assert total == len(SEED_ROWS[MODULE])
    for item in items:
        detail = service.get_entry(int(item["id"]))
        assert detail["校准结论"] == item["校准结论"]
        assert detail["status"] == item["status"]
        assert detail["精度拦截"] == item["精度拦截"]


def test_status_filter_refreshes_derived_status():
    install(SEED_ROWS[MODULE])
    service = SensorService()
    # 按待校准过滤时，规则自动标出来的记录也要查得到
    items, total = service.list_entries(status=STATUS_DUE)
    codes = {item["传感器编号"] for item in items}
    assert "SENS-0002" in codes
    assert total >= 1


def test_summary_counts():
    install(SEED_ROWS[MODULE])
    service = SensorService()
    summary = service.summary()
    assert summary["total"] == len(SEED_ROWS[MODULE])
    assert summary["精度拦截"] == 1
    assert sum(summary["status_counts"].values()) == summary["total"]
