"""校准记录接口：查询校准历史、登记新校准（保存前做日期与精度硬校验）。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.calibration import CalibrationService

router = APIRouter(prefix="/api/calibration", tags=["温感器校准记录"])

service = CalibrationService()

COLUMNS = ["校准编号", "传感器编号", "所属车辆", "校准日期", "下次校准日", "精度等级", "电池电量"]


@router.get("", response_model=PageResult[dict])
def list_records(
    keyword: str | None = Query(default=None, description="按传感器编号检索校准历史"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """校准历史倒序返回；同一传感器编号多条记录时最近一次排在最前。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_records(keyword=keyword, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("", response_model=ActionResult)
def create_record(payload: EntryPayload) -> ActionResult:
    """登记一条校准记录。

    校准日期晚于下次校准日、或精度等级不符车辆要求且仍在使用的，一律不允许保存，
    返回信息里说明具体原因；保存成功后台账按“最近一次为准”重新判定。
    """
    record, message = service.create_record(payload.values)
    if record is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=record)
