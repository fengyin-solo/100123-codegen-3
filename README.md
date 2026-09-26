# 冷链物流运输管理平台

面向冷链运输全程温控、车辆调度、门到门配送、温度异常处置、签收回单与运力结算的冷链运输管理后台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 车辆档案 | `fleet` | 冷链车 | 车辆编号、车牌号码、车型类别 |
| 司机管理 | `driver` | 驾驶员 | 驾驶员编号、驾驶员姓名、驾驶证号 |
| 运输委托 | `order` | 运输委托单 | 委托编号、委托方、起运地址 |
| 运力调度 | `dispatch3` | 调度任务 | 调度编号、关联委托、指派车辆 |
| 温控监测 | `temp` | 温度记录 | 记录编号、关联调度、温区编号 |
| 门到门配送 | `door` | 配送任务 | 任务编号、关联调度、配送站点 |
| 回单管理 | `returntrip` | 回执单 | 回单编号、关联任务、签收方 |
| 异常处置 | `abnormal2` | 异常记录 | 异常编号、异常类型、关联任务 |
| 续运中转 | `renew` | 中转记录 | 中转编号、关联任务、中转站点 |
| 制冷机组 | `refriger` | 制冷机组 | 机组编号、所属车辆、机组型号 |
| 温控箱体 | `box` | 温控箱体 | 箱体编号、箱体类型、内部容积 |
| 运输路线 | `route` | 路线方案 | 路线编号、出发地、目的地 |
| 温感器管理 | `sensor` | 温度传感器 | 传感器编号、所属车辆、传感器型号、精度等级、校准日期、下次校准日、电池电量 |
| 校准记录 | `calibration` | 传感器校准记录 | 校准编号、传感器编号、校准日期、下次校准日、精度等级 |
| 运输费用 | `cost` | 费用记录 | 费用编号、关联任务、费用类别 |
| 委托方管理 | `client2` | 委托方 | 委托方编号、委托方名称、企业类别 |
| 出车检查 | `checkin` | 检查记录 | 检查编号、检查车辆、检查日期 |
| 事故记录 | `accident` | 事故记录 | 事故编号、关联任务、事故类型 |
| 途中核查 | `roadcheck` | 途中核查 | 核查编号、关联调度、核查时间 |
| 车厢清洗 | `clean2` | 清洗记录 | 清洗编号、清洗车辆、清洗方式 |
| 合作合同 | `contract2` | 运输合同 | 合同编号、签约双方、合同类型 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 温感器校准判定口径

判定规则集中在 `backend/app/services/sensor_rules.py`（纯函数），台账列表与传感器详情
共用 `SensorService.build_view` 一个出口，结论天然一致。规则如下：

1. 下次校准日距今天**不足所属车辆阈值**（默认 30 天）的传感器自动标为「待校准」，
   等于阈值当天不算临期；车辆差异化阈值与精度要求在 `VEHICLE_RULES` 中按所属车辆配置。
2. **已停用**与**电量不足**（低于 20%）的传感器不参与到期判定。
3. 传感器精度等级不满足所属车辆要求且仍在使用（未停用）的，判为「精度不符」，
   台账拦截使用，校准记录保存也会被拒绝。
4. 同一传感器编号在校准记录里出现多次时，以**最近一次校准日期**的记录为准回写台账。
5. 校准记录保存时：校准日期晚于下次校准日的数据不允许保存，返回里说明具体原因。
6. 服务启动时执行 `SensorService().reconcile_all()`，对既有传感器数据按新口径
   统一重新标一遍（幂等，可重复执行）。

规则单元测试（固定“今天”为 2026-09-26）：

```bash
cd backend
python3 -m unittest discover -s tests -v
```
