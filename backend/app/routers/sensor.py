"""温感器管理接口：维护温度传感器，覆盖偏移预警、安排校准、停用传感器等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.sensor import SensorService

router = APIRouter(prefix="/api/sensor", tags=["温感器管理"])

service = SensorService()

LIST_FIELDS = ["传感器编号", "所属车辆", "传感器型号", "精度等级", "校准日期", "下次校准日", "电池电量", "传感器状态"]
STATUSES = ["正常", "数据偏移", "待校准", "已停用"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按传感器编号检索"),
    status: str | None = Query(default=None, description="正常、数据偏移、待校准、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按传感器编号与状态过滤温感器管理列表；没有数据时返回空页，不报错。

    返回的每条记录都会按校准口径给出「校准结论」，与详情接口同口径。
    """
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def summary() -> dict[str, Any]:
    """校准口径汇总：各状态传感器数量与精度拦截数量，供台账看板提示。"""
    return service.summary()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出温感器管理清单：返回当前全量数据（含校准结论）。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "sensor", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条温度传感器明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"温度传感器 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条温度传感器。

    校准日期晚于下次校准日、精度等级不符在用要求的数据不允许保存，
    并逐条说明原因。
    """
    entry, errors = service.create_entry(payload.values)
    if errors:
        return ActionResult(ok=False, message="；".join(errors))
    return ActionResult(ok=True, message="温度传感器已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条温度传感器执行偏移预警、安排校准、停用传感器；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
