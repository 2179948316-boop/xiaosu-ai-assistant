"""Agent 工具注册表 - 定义 LLM 可调用的工具 Schema 与执行器

工具列表：
  - get_employee_info   员工信息（部门/级别/薪资）
  - get_attendance      考勤（迟到/请假/缺勤/加班）
  - get_orders          订单（支付/退款）
  - get_current_time    当前时间（北京时间）
  - search_kb           知识库检索（与 RAG 共用混合检索管线）

执行器通过内部 HTTP 调用 Mock 数据服务（MOCK_API_BASE），模拟真实
Agent 调用公司内部系统的方式。工具执行异常不会抛出，而是把错误信息
作为结果回填给 LLM，由模型决定重试或向用户说明（降级兜底策略）。
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List

import httpx

from app.config import get_settings
from app.services.rag_service import retrieve_context

settings = get_settings()
logger = logging.getLogger(__name__)

# ============ 工具 Schema（OpenAI function calling 格式，Ollama 原生兼容） ============

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_employee_info",
            "description": "查询员工基本信息：部门、职级、基本工资、入职日期。用户询问某位员工是谁、在哪个部门、薪资多少时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "emp_id": {"type": "integer", "description": "员工编号，例如 1001"},
                },
                "required": ["emp_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_attendance",
            "description": "查询员工考勤记录，可按日期范围过滤。返回每日上下班打卡时间、状态（normal 正常/late 迟到/leave 请假/absent 缺勤）和加班小时数。询问迟到、请假、缺勤、加班、出勤情况时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "emp_id": {"type": "integer", "description": "员工编号（可选，缺省返回全部员工）"},
                    "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD（可选）"},
                    "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD（可选）"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_orders",
            "description": "查询员工订单记录，可按日期范围过滤。返回订单号、客户、金额、状态（paid 已支付/refunded 已退款）。询问订单、销售额、成交、退款时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "emp_id": {"type": "integer", "description": "员工编号（可选）"},
                    "start_date": {"type": "string", "description": "开始日期 YYYY-MM-DD（可选）"},
                    "end_date": {"type": "string", "description": "结束日期 YYYY-MM-DD（可选）"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "获取当前日期和时间（北京时间 Asia/Shanghai）。用户询问今天是几号、现在几点、本周周几时使用。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "在公司知识库中检索与问题相关的文档片段（规章制度、产品说明等已上传文档）。问题涉及文档内容、且无法用员工/考勤/订单工具回答时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词或完整问题"},
                },
                "required": ["query"],
            },
        },
    },
]

TOOL_NAMES = [t["function"]["name"] for t in TOOL_SCHEMAS]


# ============ 工具执行器 ============

async def _http_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """内部 HTTP 调用 Mock 数据服务；失败时返回错误结构而非抛出"""
    url = f"{settings.MOCK_API_BASE}{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 404:
                return {"error": resp.json().get("detail", "资源不存在")}
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Mock API 调用失败 {url}: {e}")
        return {"error": f"内部数据服务暂不可用: {str(e)}"}


async def _get_employee_info(args: Dict[str, Any]) -> str:
    emp_id = args.get("emp_id")
    if emp_id is None:
        return json.dumps({"error": "缺少 emp_id 参数"}, ensure_ascii=False)
    data = await _http_get(f"/api/mock/employee/{emp_id}", {})
    return json.dumps(data, ensure_ascii=False)


async def _get_attendance(args: Dict[str, Any]) -> str:
    params = {k: v for k, v in args.items() if v is not None}
    data = await _http_get("/api/mock/attendance", params)
    return json.dumps(data, ensure_ascii=False)


async def _get_orders(args: Dict[str, Any]) -> str:
    params = {k: v for k, v in args.items() if v is not None}
    data = await _http_get("/api/mock/orders", params)
    return json.dumps(data, ensure_ascii=False)


async def _get_current_time(args: Dict[str, Any]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return json.dumps({"current_time": now, "timezone": "Asia/Shanghai"}, ensure_ascii=False)


async def _search_kb(args: Dict[str, Any], kb_id: int) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return json.dumps({"error": "缺少 query 参数"}, ensure_ascii=False)
    try:
        sources = await retrieve_context(kb_id, query)
    except Exception as e:
        logger.error(f"search_kb 检索失败: {e}")
        return json.dumps({"error": f"知识库检索失败: {str(e)}"}, ensure_ascii=False)
    if not sources:
        return json.dumps({"found": False, "sources": []}, ensure_ascii=False)
    return json.dumps({
        "found": True,
        "top1_score": round(float(sources[0]["score"]), 4),
        "sources": [
            {
                "filename": s["metadata"].get("filename", "未知"),
                "chunk_index": s["metadata"].get("chunk_index", 0),
                "chunk_id": s.get("id", ""),
                "score": round(float(s["score"]), 4),
                "text": s["text"][:500],
            }
            for s in sources
        ],
    }, ensure_ascii=False)


async def execute_tool(name: str, arguments: Dict[str, Any], kb_id: int) -> str:
    """执行工具，返回结果 JSON 字符串（工具阶段非流式，直接回填给 LLM）"""
    if name == "get_employee_info":
        return await _get_employee_info(arguments)
    if name == "get_attendance":
        return await _get_attendance(arguments)
    if name == "get_orders":
        return await _get_orders(arguments)
    if name == "get_current_time":
        return await _get_current_time(arguments)
    if name == "search_kb":
        return await _search_kb(arguments, kb_id)
    return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)
