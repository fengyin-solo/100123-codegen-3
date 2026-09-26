"""业务模块路由汇总。

这里统一按别名导入再暴露 ROUTERS：模块名有可能和内置名撞车（某个业务模块就叫 dict、list
这种名字时），按名字直接 import 会把内置类型覆盖掉，函数注解在运行时求值就会报
'module' object is not subscriptable。
"""
from __future__ import annotations

from app.routers import fleet as router_fleet
from app.routers import driver as router_driver
from app.routers import order as router_order
from app.routers import dispatch3 as router_dispatch3
from app.routers import temp as router_temp
from app.routers import door as router_door
from app.routers import returntrip as router_returntrip
from app.routers import abnormal2 as router_abnormal2
from app.routers import renew as router_renew
from app.routers import refriger as router_refriger
from app.routers import box as router_box
from app.routers import route as router_route
from app.routers import sensor as router_sensor
from app.routers import calibration as router_calibration
from app.routers import cost as router_cost
from app.routers import client2 as router_client2
from app.routers import checkin as router_checkin
from app.routers import accident as router_accident
from app.routers import roadcheck as router_roadcheck
from app.routers import clean2 as router_clean2
from app.routers import contract2 as router_contract2

ROUTERS = [router_fleet, router_driver, router_order, router_dispatch3, router_temp, router_door, router_returntrip, router_abnormal2, router_renew, router_refriger, router_box, router_route, router_sensor, router_calibration, router_cost, router_client2, router_checkin, router_accident, router_roadcheck, router_clean2, router_contract2]
