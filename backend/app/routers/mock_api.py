"""Mock 数据服务 - Agent 工具调用的内部数据源

模拟公司内部系统的只读接口（curl 可直接访问），数据为演示用 mock：
  - GET /api/mock/employee/{emp_id}        员工信息（部门/级别/薪资）
  - GET /api/mock/attendance?emp_id=&start_date=&end_date=   考勤记录（含迟到/加班/请假边界）
  - GET /api/mock/orders?emp_id=&start_date=&end_date=       订单记录（含退款边界）

边界数据说明（面试演示点）：
  - 迟到：attendance.status = late（上班 9:30 之后打卡）
  - 加班：attendance.overtime_hours > 0
  - 请假：attendance.status = leave
  - 退款：orders.status = refunded
"""
from fastapi import APIRouter, HTTPException
from datetime import date as date_cls, datetime
from typing import List, Optional

router = APIRouter(prefix="/api/mock", tags=["Mock 数据服务（Agent 工具）"])

# ============ 员工数据（12 人） ============
EMPLOYEES: List[dict] = [
    {"emp_id": 1001, "name": "张伟", "department": "技术部", "level": "P6", "base_salary": 28000, "hire_date": "2021-03-15"},
    {"emp_id": 1002, "name": "李娜", "department": "技术部", "level": "P5", "base_salary": 22000, "hire_date": "2022-06-01"},
    {"emp_id": 1003, "name": "王强", "department": "产品部", "level": "P6", "base_salary": 26000, "hire_date": "2020-11-02"},
    {"emp_id": 1004, "name": "赵敏", "department": "产品部", "level": "P5", "base_salary": 21000, "hire_date": "2023-02-20"},
    {"emp_id": 1005, "name": "刘洋", "department": "市场部", "level": "P4", "base_salary": 15000, "hire_date": "2023-08-01"},
    {"emp_id": 1006, "name": "陈静", "department": "市场部", "level": "P5", "base_salary": 18000, "hire_date": "2022-01-10"},
    {"emp_id": 1007, "name": "杨磊", "department": "财务部", "level": "P7", "base_salary": 35000, "hire_date": "2019-05-06"},
    {"emp_id": 1008, "name": "周婷", "department": "财务部", "level": "P5", "base_salary": 19000, "hire_date": "2022-09-12"},
    {"emp_id": 1009, "name": "吴刚", "department": "人事部", "level": "P6", "base_salary": 24000, "hire_date": "2021-07-19"},
    {"emp_id": 1010, "name": "郑洁", "department": "人事部", "level": "P4", "base_salary": 14000, "hire_date": "2024-01-08"},
    {"emp_id": 1011, "name": "孙浩", "department": "技术部", "level": "P7", "base_salary": 38000, "hire_date": "2018-10-22"},
    {"emp_id": 1012, "name": "林芳", "department": "客服部", "level": "P3", "base_salary": 9000, "hire_date": "2024-06-03"},
]

# ============ 考勤数据（近 10 个工作日 × 6 人，覆盖迟到/加班/请假/缺勤） ============
ATTENDANCE: List[dict] = [
    # 张伟(1001)：周一迟到 1 次、周五加班
    {"emp_id": 1001, "date": "2026-08-03", "check_in": "09:42", "check_out": "18:30", "status": "late", "overtime_hours": 0},
    {"emp_id": 1001, "date": "2026-08-04", "check_in": "09:10", "check_out": "18:12", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1001, "date": "2026-08-05", "check_in": "09:02", "check_out": "18:05", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1001, "date": "2026-08-06", "check_in": "09:15", "check_out": "18:40", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1001, "date": "2026-08-07", "check_in": "09:05", "check_out": "21:30", "status": "normal", "overtime_hours": 3.0},
    {"emp_id": 1001, "date": "2026-08-10", "check_in": "09:20", "check_out": "18:20", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1001, "date": "2026-08-11", "check_in": "09:08", "check_out": "18:15", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1001, "date": "2026-08-12", "check_in": "09:33", "check_out": "18:10", "status": "late", "overtime_hours": 0},
    {"emp_id": 1001, "date": "2026-08-13", "check_in": "09:01", "check_out": "18:02", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1001, "date": "2026-08-14", "check_in": "09:25", "check_out": "19:45", "status": "normal", "overtime_hours": 1.5},
    # 李娜(1002)：周三请假、周四补卡
    {"emp_id": 1002, "date": "2026-08-03", "check_in": "09:00", "check_out": "18:00", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1002, "date": "2026-08-04", "check_in": "09:05", "check_out": "18:08", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1002, "date": "2026-08-05", "check_in": None, "check_out": None, "status": "leave", "overtime_hours": 0},
    {"emp_id": 1002, "date": "2026-08-06", "check_in": "09:12", "check_out": "18:20", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1002, "date": "2026-08-07", "check_in": "09:03", "check_out": "18:10", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1002, "date": "2026-08-10", "check_in": "09:40", "check_out": "18:35", "status": "late", "overtime_hours": 0},
    {"emp_id": 1002, "date": "2026-08-11", "check_in": "09:09", "check_out": "18:00", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1002, "date": "2026-08-12", "check_in": "09:02", "check_out": "18:05", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1002, "date": "2026-08-13", "check_in": "09:11", "check_out": "18:14", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1002, "date": "2026-08-14", "check_in": "09:00", "check_out": "18:03", "status": "normal", "overtime_hours": 0},
    # 王强(1003)：缺勤 1 天
    {"emp_id": 1003, "date": "2026-08-03", "check_in": "09:01", "check_out": "18:02", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1003, "date": "2026-08-04", "check_in": None, "check_out": None, "status": "absent", "overtime_hours": 0},
    {"emp_id": 1003, "date": "2026-08-05", "check_in": "09:06", "check_out": "18:01", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1003, "date": "2026-08-06", "check_in": "09:20", "check_out": "20:00", "status": "normal", "overtime_hours": 1.5},
    {"emp_id": 1003, "date": "2026-08-07", "check_in": "09:02", "check_out": "18:06", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1003, "date": "2026-08-10", "check_in": "09:10", "check_out": "18:10", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1003, "date": "2026-08-11", "check_in": "09:03", "check_out": "18:03", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1003, "date": "2026-08-12", "check_in": "09:08", "check_out": "18:09", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1003, "date": "2026-08-13", "check_in": "09:00", "check_out": "18:00", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1003, "date": "2026-08-14", "check_in": "09:12", "check_out": "18:12", "status": "normal", "overtime_hours": 0},
    # 刘洋(1005)：迟到 3 次（高频迟到样例）
    {"emp_id": 1005, "date": "2026-08-03", "check_in": "09:45", "check_out": "18:30", "status": "late", "overtime_hours": 0},
    {"emp_id": 1005, "date": "2026-08-04", "check_in": "09:38", "check_out": "18:20", "status": "late", "overtime_hours": 0},
    {"emp_id": 1005, "date": "2026-08-05", "check_in": "09:02", "check_out": "18:05", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1005, "date": "2026-08-06", "check_in": "09:31", "check_out": "18:15", "status": "late", "overtime_hours": 0},
    {"emp_id": 1005, "date": "2026-08-07", "check_in": "09:10", "check_out": "18:10", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1005, "date": "2026-08-10", "check_in": "09:05", "check_out": "22:00", "status": "normal", "overtime_hours": 3.5},
    {"emp_id": 1005, "date": "2026-08-11", "check_in": "09:00", "check_out": "18:00", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1005, "date": "2026-08-12", "check_in": "09:07", "check_out": "18:07", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1005, "date": "2026-08-13", "check_in": "09:03", "check_out": "18:03", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1005, "date": "2026-08-14", "check_in": "09:09", "check_out": "18:09", "status": "normal", "overtime_hours": 0},
    # 孙浩(1011)：频繁加班样例
    {"emp_id": 1011, "date": "2026-08-03", "check_in": "09:00", "check_out": "20:30", "status": "normal", "overtime_hours": 2.5},
    {"emp_id": 1011, "date": "2026-08-04", "check_in": "09:02", "check_out": "21:00", "status": "normal", "overtime_hours": 3.0},
    {"emp_id": 1011, "date": "2026-08-05", "check_in": "09:01", "check_out": "19:30", "status": "normal", "overtime_hours": 1.5},
    {"emp_id": 1011, "date": "2026-08-06", "check_in": "09:05", "check_out": "20:00", "status": "normal", "overtime_hours": 2.0},
    {"emp_id": 1011, "date": "2026-08-07", "check_in": "09:03", "check_out": "18:00", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1011, "date": "2026-08-10", "check_in": "09:00", "check_out": "21:30", "status": "normal", "overtime_hours": 3.5},
    {"emp_id": 1011, "date": "2026-08-11", "check_in": "09:10", "check_out": "18:10", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1011, "date": "2026-08-12", "check_in": "09:02", "check_out": "20:15", "status": "normal", "overtime_hours": 2.0},
    {"emp_id": 1011, "date": "2026-08-13", "check_in": "09:04", "check_out": "18:04", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1011, "date": "2026-08-14", "check_in": "09:01", "check_out": "19:00", "status": "normal", "overtime_hours": 1.0},
    # 林芳(1012)：入职新人样例
    {"emp_id": 1012, "date": "2026-08-03", "check_in": "09:00", "check_out": "18:00", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1012, "date": "2026-08-04", "check_in": "09:05", "check_out": "18:05", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1012, "date": "2026-08-05", "check_in": "09:10", "check_out": "18:10", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1012, "date": "2026-08-06", "check_in": "09:02", "check_out": "18:02", "status": "normal", "overtime_hours": 0},
    {"emp_id": 1012, "date": "2026-08-07", "check_in": "09:08", "check_out": "18:08", "status": "normal", "overtime_hours": 0},
]

# ============ 订单数据（近 7 天，含退款） ============
ORDERS: List[dict] = [
    {"order_id": "SO20260803001", "emp_id": 1001, "customer": "华信科技", "amount": 12800.00, "status": "paid", "date": "2026-08-03"},
    {"order_id": "SO20260803002", "emp_id": 1002, "customer": "云杉网络", "amount": 5600.00, "status": "paid", "date": "2026-08-03"},
    {"order_id": "SO20260804001", "emp_id": 1001, "customer": "星河数据", "amount": 23400.00, "status": "paid", "date": "2026-08-04"},
    {"order_id": "SO20260804002", "emp_id": 1005, "customer": "蓝海咨询", "amount": 3200.00, "status": "refunded", "date": "2026-08-04"},
    {"order_id": "SO20260805001", "emp_id": 1003, "customer": "华信科技", "amount": 8900.00, "status": "paid", "date": "2026-08-05"},
    {"order_id": "SO20260805002", "emp_id": 1002, "customer": "启明教育", "amount": 4500.00, "status": "refunded", "date": "2026-08-05"},
    {"order_id": "SO20260806001", "emp_id": 1001, "customer": "中科智联", "amount": 35600.00, "status": "paid", "date": "2026-08-06"},
    {"order_id": "SO20260806002", "emp_id": 1006, "customer": "瑞丰制造", "amount": 7200.00, "status": "paid", "date": "2026-08-06"},
    {"order_id": "SO20260807001", "emp_id": 1003, "customer": "云杉网络", "amount": 11200.00, "status": "paid", "date": "2026-08-07"},
    {"order_id": "SO20260807002", "emp_id": 1009, "customer": "蓝海咨询", "amount": 6800.00, "status": "refunded", "date": "2026-08-07"},
    {"order_id": "SO20260810001", "emp_id": 1005, "customer": "华信科技", "amount": 15000.00, "status": "paid", "date": "2026-08-10"},
    {"order_id": "SO20260810002", "emp_id": 1011, "customer": "星河数据", "amount": 9800.00, "status": "paid", "date": "2026-08-10"},
    {"order_id": "SO20260811001", "emp_id": 1001, "customer": "启明教育", "amount": 27600.00, "status": "paid", "date": "2026-08-11"},
    {"order_id": "SO20260811002", "emp_id": 1007, "customer": "中科智联", "amount": 4200.00, "status": "refunded", "date": "2026-08-11"},
    {"order_id": "SO20260812001", "emp_id": 1002, "customer": "瑞丰制造", "amount": 6400.00, "status": "paid", "date": "2026-08-12"},
    {"order_id": "SO20260812002", "emp_id": 1006, "customer": "华信科技", "amount": 18500.00, "status": "paid", "date": "2026-08-12"},
    {"order_id": "SO20260813001", "emp_id": 1003, "customer": "云杉网络", "amount": 9300.00, "status": "paid", "date": "2026-08-13"},
    {"order_id": "SO20260813002", "emp_id": 1011, "customer": "蓝海咨询", "amount": 5400.00, "status": "refunded", "date": "2026-08-13"},
    {"order_id": "SO20260814001", "emp_id": 1001, "customer": "星河数据", "amount": 31200.00, "status": "paid", "date": "2026-08-14"},
    {"order_id": "SO20260814002", "emp_id": 1005, "customer": "中科智联", "amount": 8800.00, "status": "paid", "date": "2026-08-14"},
]

_EMPLOYEE_MAP = {e["emp_id"]: e for e in EMPLOYEES}


def _parse_date(value: str) -> date_cls:
    return datetime.strptime(value, "%Y-%m-%d").date()


@router.get("/employee/{emp_id}")
async def get_employee(emp_id: int):
    """员工信息：部门 / 级别 / 基本工资 / 入职日期"""
    emp = _EMPLOYEE_MAP.get(emp_id)
    if not emp:
        raise HTTPException(status_code=404, detail=f"员工 {emp_id} 不存在")
    return emp


@router.get("/attendance")
async def get_attendance(
    emp_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """
    考勤记录列表。
    status: normal(正常) / late(迟到) / leave(请假) / absent(缺勤)
    overtime_hours: 加班小时数（>0 表示加班）
    """
    records = ATTENDANCE
    if emp_id is not None:
        records = [r for r in records if r["emp_id"] == emp_id]
    if start_date:
        start = _parse_date(start_date)
        records = [r for r in records if _parse_date(r["date"]) >= start]
    if end_date:
        end = _parse_date(end_date)
        records = [r for r in records if _parse_date(r["date"]) <= end]
    return {"total": len(records), "records": records}


@router.get("/orders")
async def get_orders(
    emp_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """
    订单列表。
    status: paid(已支付) / refunded(已退款) / pending(待支付)
    """
    records = ORDERS
    if emp_id is not None:
        records = [r for r in records if r["emp_id"] == emp_id]
    if start_date:
        start = _parse_date(start_date)
        records = [r for r in records if _parse_date(r["date"]) >= start]
    if end_date:
        end = _parse_date(end_date)
        records = [r for r in records if _parse_date(r["date"]) <= end]
    return {"total": len(records), "records": records}
