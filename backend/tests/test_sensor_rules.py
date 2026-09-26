"""温感器校准规则的单元测试：固定“今天”为 2026-09-26，结论可重复。

运行：cd backend && .venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import copy
import unittest
from datetime import date

from app.services.calibration import CalibrationService
from app.services.sensor import SensorService
from app.services.sensor_rules import (
    DEFAULT_DUE_DAYS,
    LOW_BATTERY_PERCENT,
    evaluate_calibration,
    latest_calibration,
    normalize_precision,
    parse_battery,
    parse_date,
    precision_matches,
    vehicle_rule,
)
from app.store import store

TODAY = date(2026, 9, 26)


def make_sensor(**overrides):
    base = {
        "id": 1,
        "status": "正常",
        "传感器编号": "SENS-T1",
        "所属车辆": "苏D-默认车辆",
        "传感器型号": "RS-Probe-X1",
        "精度等级": "B级",
        "校准日期": "2026-08-01",
        "下次校准日": "2026-12-01",
        "电池电量": "80%",
    }
    base.update(overrides)
    return base


class DateAndBatteryParsingTests(unittest.TestCase):
    def test_parse_date_formats(self):
        self.assertEqual(parse_date("2026-09-26"), TODAY)
        self.assertEqual(parse_date("2026/09/26"), TODAY)
        self.assertIsNone(parse_date(""))
        self.assertIsNone(parse_date("随便写的"))
        self.assertIsNone(parse_date(None))

    def test_parse_battery_variants(self):
        self.assertEqual(parse_battery("85%"), 85)
        self.assertEqual(parse_battery(85), 85)
        self.assertEqual(parse_battery(0.2), 20)
        self.assertEqual(parse_battery("12%"), 12)
        self.assertIsNone(parse_battery("未知"))

    def test_precision_normalize_and_compare(self):
        self.assertEqual(normalize_precision("a级"), "A")
        self.assertEqual(normalize_precision("二级"), "B")
        self.assertTrue(precision_matches("A", "B"))
        self.assertTrue(precision_matches("B", "B"))
        self.assertFalse(precision_matches("C", "B"))
        self.assertFalse(precision_matches(None, "A"))
        self.assertTrue(precision_matches("C", None))


class VehicleThresholdTests(unittest.TestCase):
    def test_thresholds_are_per_vehicle(self):
        self.assertEqual(vehicle_rule("京A-冷链车1")["due_days"], 45)
        self.assertEqual(vehicle_rule("沪B-冷链车2")["due_days"], 15)
        self.assertEqual(vehicle_rule("粤C-冷藏车3")["due_days"], 30)
        self.assertEqual(vehicle_rule("苏D-未配置车辆")["due_days"], DEFAULT_DUE_DAYS)
        self.assertEqual(vehicle_rule("京A-冷链车1")["required_precision"], "A")

    def test_under_threshold_marks_due(self):
        sensor = make_sensor(下次校准日="2026-10-20")  # 24 天，默认阈值 30
        verdict = evaluate_calibration(sensor, today=TODAY)
        self.assertTrue(verdict["due"])
        self.assertEqual(verdict["conclusion"], "待校准")
        self.assertEqual(verdict["days_left"], 24)
        self.assertIn("仅剩 24 天", verdict["reason"])

    def test_exactly_threshold_is_not_due(self):
        # “不足 30 天”：等于 30 天不算
        sensor = make_sensor(下次校准日="2026-10-26")
        verdict = evaluate_calibration(sensor, today=TODAY)
        self.assertFalse(verdict["due"])
        self.assertEqual(verdict["conclusion"], "正常")

    def test_overdue_is_due(self):
        sensor = make_sensor(下次校准日="2026-09-20")  # 已过期 6 天
        verdict = evaluate_calibration(sensor, today=TODAY)
        self.assertTrue(verdict["due"])
        self.assertIn("6 天前过期", verdict["reason"])

    def test_vehicle_threshold_changes_boundary(self):
        # 同样剩 20 天：沪B 阈值 15 → 不临期；默认车阈值 30 → 临期
        sensor_b = make_sensor(所属车辆="沪B-冷链车2", 下次校准日="2026-10-16")
        self.assertFalse(evaluate_calibration(sensor_b, today=TODAY)["due"])
        sensor_d = make_sensor(下次校准日="2026-10-16")
        self.assertTrue(evaluate_calibration(sensor_d, today=TODAY)["due"])

    def test_low_battery_excluded_from_due_judgement(self):
        sensor = make_sensor(下次校准日="2026-10-01", 电池电量="12%")  # 仅 5 天
        verdict = evaluate_calibration(sensor, today=TODAY)
        self.assertFalse(verdict["due"])
        self.assertTrue(verdict["low_battery"])
        self.assertEqual(verdict["conclusion"], "低电量免判")
        self.assertEqual(verdict["threshold_days"], 30)

    def test_battery_at_threshold_still_judged(self):
        sensor = make_sensor(下次校准日="2026-10-01", 电池电量="20%")
        verdict = evaluate_calibration(sensor, today=TODAY)
        self.assertTrue(verdict["due"])
        self.assertFalse(verdict["low_battery"])

    def test_disabled_excluded_even_when_overdue(self):
        sensor = make_sensor(status="已停用", 下次校准日="2026-01-01", 电池电量="8%")
        verdict = evaluate_calibration(sensor, today=TODAY)
        self.assertFalse(verdict["due"])
        self.assertEqual(verdict["conclusion"], "已停用")

    def test_missing_next_date_does_not_count_as_due(self):
        sensor = make_sensor(下次校准日="")
        verdict = evaluate_calibration(sensor, today=TODAY)
        self.assertFalse(verdict["due"])
        self.assertEqual(verdict["conclusion"], "无校准计划")
        self.assertIsNone(verdict["days_left"])


class PrecisionRuleTests(unittest.TestCase):
    def test_precision_mismatch_in_use_is_flagged(self):
        sensor = make_sensor(所属车辆="京A-冷链车1", 精度等级="B级")
        verdict = evaluate_calibration(sensor, today=TODAY)
        self.assertTrue(verdict["precision_mismatch"])
        self.assertEqual(verdict["conclusion"], "精度不符")
        self.assertIn("不得继续使用", verdict["reason"])

    def test_precision_ok_when_better_than_required(self):
        sensor = make_sensor(所属车辆="京A-冷链车1", 精度等级="A级")
        verdict = evaluate_calibration(sensor, today=TODAY)
        self.assertFalse(verdict["precision_mismatch"])

    def test_disabled_sensor_exempt_from_precision_rule(self):
        sensor = make_sensor(所属车辆="京A-冷链车1", 精度等级="C级", status="已停用")
        verdict = evaluate_calibration(sensor, today=TODAY)
        self.assertFalse(verdict["precision_mismatch"])
        self.assertEqual(verdict["conclusion"], "已停用")


class LatestCalibrationTests(unittest.TestCase):
    def test_latest_record_wins(self):
        records = [
            {"校准编号": "C1", "传感器编号": "SENS-X", "校准日期": "2026-03-10", "电池电量": "40%"},
            {"校准编号": "C2", "传感器编号": "SENS-X", "校准日期": "2026-09-18", "电池电量": "64%"},
        ]
        latest = latest_calibration(records, "SENS-X")
        self.assertEqual(latest["校准编号"], "C2")

    def test_latest_record_overrides_ledger_fields(self):
        sensor = make_sensor(下次校准日="2026-09-10", 电池电量="40%")
        records = [
            {"校准编号": "C1", "传感器编号": "SENS-T1", "校准日期": "2026-03-10", "下次校准日": "2026-09-10", "电池电量": "40%"},
            {"校准编号": "C2", "传感器编号": "SENS-T1", "校准日期": "2026-09-18", "下次校准日": "2026-11-15", "电池电量": "64%"},
        ]
        verdict = evaluate_calibration(sensor, records, today=TODAY)
        self.assertEqual(verdict["next_calibration_date"], "2026-11-15")
        self.assertEqual(verdict["battery"], 64)
        self.assertEqual(verdict["latest_record_id"], "C2")
        self.assertFalse(verdict["due"])

    def test_other_sensor_records_ignored(self):
        records = [{"传感器编号": "SENS-OTHER", "校准日期": "2026-09-18"}]
        self.assertIsNone(latest_calibration(records, "SENS-T1"))


class StoreBackedRuleTests(unittest.TestCase):
    """每个用例前后深拷贝恢复 sensor / calibration 两张表，避免相互污染。"""

    def setUp(self):
        self.backup = {
            "sensor": copy.deepcopy(store.rows("sensor")),
            "calibration": copy.deepcopy(store.rows("calibration")),
        }
        self.service = SensorService()

    def tearDown(self):
        store._tables["sensor"] = self.backup["sensor"]
        store._tables["calibration"] = self.backup["calibration"]

    def test_reconcile_regrades_all_existing_sensors(self):
        result = self.service.reconcile_all(today=TODAY)
        by_no = {row["传感器编号"]: row for row in store.rows("sensor")}

        # 京A 阈值 45：剩 14 天 → 旧状态正常，自动改待校准
        self.assertEqual(by_no["SENS-0001"]["status"], "待校准")
        # 沪B 阈值 15：剩 9 天 → 待校准
        self.assertEqual(by_no["SENS-0002"]["status"], "待校准")
        # 已过期 → 待校准
        self.assertEqual(by_no["SENS-0003"]["status"], "待校准")
        # 京A 要求 A 级，实际 B 级：标记精度不符，但未临期，台账不被改成待校准
        view4 = self.service.build_view(by_no["SENS-0004"], today=TODAY)
        self.assertTrue(view4["精度不符"])
        self.assertEqual(view4["status"], "正常")
        # 低电量即使只剩 5 天也不参与到期判定，旧的待校准被清掉
        view5 = self.service.build_view(by_no["SENS-0005"], today=TODAY)
        self.assertFalse(view5["临期"])
        self.assertEqual(by_no["SENS-0005"]["status"], "正常")
        self.assertEqual(view5["校准判定"], "低电量免判")
        # 同编号两条校准记录，以 09-18 最近一次回写台账，50 天 > 沪B 阈值 15
        self.assertEqual(by_no["SENS-0006"]["校准日期"], "2026-09-18")
        self.assertEqual(by_no["SENS-0006"]["下次校准日"], "2026-11-15")
        self.assertEqual(by_no["SENS-0006"]["电池电量"], "64%")
        self.assertEqual(by_no["SENS-0006"]["status"], "正常")
        # 已停用：过期也保持停用
        self.assertEqual(by_no["SENS-0007"]["status"], "已停用")
        # 数据偏移且不临期：保留人工状态
        self.assertEqual(by_no["SENS-0008"]["status"], "数据偏移")

        self.assertEqual(result["total"], 8)
        self.assertGreaterEqual(result["due"], 3)
        self.assertGreaterEqual(result["precision_mismatch"], 1)

    def test_reconcile_is_idempotent(self):
        first = self.service.reconcile_all(today=TODAY)
        snapshot = copy.deepcopy(store.rows("sensor"))
        second = self.service.reconcile_all(today=TODAY)
        self.assertEqual(second["changed"], 0)
        self.assertEqual(store.rows("sensor"), snapshot)
        self.assertEqual(first["due"], second["due"])

    def test_list_and_detail_share_same_conclusion(self):
        self.service.reconcile_all(today=TODAY)
        items, _ = self.service.list_entries(page=1, size=100)
        for row in items:
            detail = self.service.get_entry(int(row["id"]))
            for field in ("status", "校准判定", "判定说明", "距到期天数", "精度不符", "电量不足"):
                self.assertEqual(row[field], detail[field], f"{row['传感器编号']} 的 {field} 台账与详情不一致")

    def test_duplicate_sensor_no_rejected(self):
        entry, missing, error = self.service.create_entry({
            "传感器编号": "SENS-0001", "所属车辆": "京A-冷链车1", "传感器型号": "RS-Probe-X1",
        })
        self.assertIsNone(entry)
        self.assertIn("已存在", error)
        self.assertEqual(missing, [])

    def test_disable_action_is_terminal_and_skips_due(self):
        # SENS-0001 启动重标后是临期待校准（pending=True），停用必须翻成 False
        entry, message, applied = self.service.run_action(1, "停用传感器")
        self.assertTrue(applied)
        self.assertEqual(entry["status"], "已停用")
        self.assertFalse(entry["pending"])
        self.assertEqual(entry["校准判定"], "已停用")
        # 已停用的传感器重复停用也应保持终态
        entry, _, applied = self.service.run_action(1, "停用传感器")
        self.assertTrue(applied)
        self.assertFalse(entry["pending"])

    def test_precision_mismatch_blocks_arrange_calibration(self):
        # SENS-0004：京A 要求 A 级、实际 B 级，仍在用
        entry, message, applied = self.service.run_action(4, "安排校准")
        self.assertFalse(applied, "动作被拦截，不应落库")
        self.assertIsNotNone(entry)
        self.assertTrue(entry["精度不符"])
        self.assertIn("精度等级不符", message)

    def test_precision_mismatch_allows_offset_warning_and_disable(self):
        # 负面上报与停用不是“恢复使用”，不拦
        entry, _, applied = self.service.run_action(4, "偏移预警")
        self.assertTrue(applied)
        self.assertEqual(entry["status"], "数据偏移")
        entry, _, applied = self.service.run_action(4, "停用传感器")
        self.assertTrue(applied)
        self.assertEqual(entry["status"], "已停用")

    def test_due_sensor_arrange_calibration_stays_due(self):
        # SENS-0002 临期：动作执行，但规则结论不被冲掉
        entry, message, applied = self.service.run_action(2, "安排校准")
        self.assertTrue(applied)
        self.assertEqual(entry["status"], "待校准")
        self.assertIn("仍按规则判为待校准", message)


class CalibrationSaveTests(unittest.TestCase):
    def setUp(self):
        self.backup = {
            "sensor": copy.deepcopy(store.rows("sensor")),
            "calibration": copy.deepcopy(store.rows("calibration")),
        }
        self.service = CalibrationService()

    def tearDown(self):
        store._tables["sensor"] = self.backup["sensor"]
        store._tables["calibration"] = self.backup["calibration"]

    def test_calibration_date_after_next_date_is_blocked(self):
        record, message = self.service.create_record({
            "传感器编号": "SENS-0001",
            "校准日期": "2026-10-01",
            "下次校准日": "2026-09-15",
            "精度等级": "A级",
        })
        self.assertIsNone(record)
        self.assertIn("晚于下次校准日", message)

    def test_precision_mismatch_in_use_is_blocked(self):
        record, message = self.service.create_record({
            "传感器编号": "SENS-0004",  # 京A 要求 A 级
            "校准日期": "2026-09-01",
            "下次校准日": "2027-03-01",
            "精度等级": "C级",
        })
        self.assertIsNone(record)
        self.assertIn("精度等级", message)
        self.assertIn("不得保存", message)

    def test_disabled_sensor_precision_record_allowed(self):
        record, message = self.service.create_record({
            "传感器编号": "SENS-0007",  # 已停用，C 级不再拦截
            "校准日期": "2026-09-01",
            "下次校准日": "2027-03-01",
            "精度等级": "C级",
        })
        self.assertIsNotNone(record, message)

    def test_unknown_sensor_blocked(self):
        record, message = self.service.create_record({
            "传感器编号": "SENS-NOPE",
            "校准日期": "2026-09-01",
            "下次校准日": "2027-03-01",
            "精度等级": "A级",
        })
        self.assertIsNone(record)
        self.assertIn("台账中不存在", message)

    def test_missing_fields_blocked(self):
        record, message = self.service.create_record({"传感器编号": "SENS-0001"})
        self.assertIsNone(record)
        self.assertIn("缺少必填字段", message)

    def test_save_applies_latest_record_to_ledger(self):
        record, message = self.service.create_record({
            "传感器编号": "SENS-0002",
            "校准日期": "2026-09-25",
            "下次校准日": "2027-03-25",
            "精度等级": "B级",
            "电池电量": "90%",
        })
        self.assertIsNotNone(record, message)
        sensor = next(row for row in store.rows("sensor") if row["传感器编号"] == "SENS-0002")
        self.assertEqual(sensor["下次校准日"], "2027-03-25")
        self.assertEqual(sensor["电池电量"], "90%")
        self.assertEqual(record["传感器编号"], "SENS-0002")


if __name__ == "__main__":
    unittest.main()
