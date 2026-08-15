"""飞书机器人独立进程入口（Phase 4）

与 Web API 同仓库、独立运行：
    uv run python bot_service.py

架构要点：
  - lark-oapi 采用 **长连接（WebSocket）模式**，无需公网回调地址
  - SDK 事件回调运行在子线程，而 Agent/DB 管线是 asyncio；
    因此启动一个专用事件循环线程，回调通过 run_coroutine_threadsafe 投递
  - 全局 try/except 兜底：任何异常都回复友好文案，绝不让进程静默吞错

依赖 .env 中的 FEISHU_APP_ID / FEISHU_APP_SECRET。
"""
import asyncio
import json
import logging
import threading

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from app.config import get_settings
from app.log_config import setup_logging
from app.services import feishu_bot

settings = get_settings()
setup_logging()
logger = logging.getLogger("feishu_bot")

# 专用事件循环：所有 asyncio 工作（DB / Agent / Redis）都在此循环上执行
_loop = asyncio.new_event_loop()


def _run_loop() -> None:
    asyncio.set_event_loop(_loop)
    _loop.run_forever()


def _send_reply(message_id: str, msg_type: str, content: str) -> None:
    """以"引用回复"方式回消息（群聊会形成话题，单聊也适用）。"""
    client = lark.Client.builder() \
        .app_id(settings.FEISHU_APP_ID) \
        .app_secret(settings.FEISHU_APP_SECRET) \
        .log_level(lark.LogLevel.INFO) \
        .build()
    request = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(
            ReplyMessageRequestBody.builder()
            .msg_type(msg_type)
            .content(content)
            .build()
        ).build()
    response = client.im.v1.message.reply(request)
    if not response.success():
        logger.error(
            f"回复失败 code={response.code} msg={response.msg} "
            f"log_id={getattr(response, 'get_log_id', lambda: '')()}"
        )


async def _handle_message_async(data: P2ImMessageReceiveV1) -> None:
    """异步处理一条消息（运行在专用事件循环上）。"""
    event = data.event
    message = event.message
    sender = event.sender

    message_id = message.message_id
    chat_id = message.chat_id
    chat_type = message.chat_type          # "p2p" | "group"
    message_type = message.message_type    # 仅处理 text
    content = message.content or ""
    open_id = sender.sender_id.open_id if sender and sender.sender_id else ""

    # 幂等防重放
    if await feishu_bot.is_duplicate(message_id):
        logger.info(f"重复事件已忽略: message_id={message_id}")
        return

    # 仅处理文本消息
    if message_type != "text":
        _send_reply(message_id, "text", json.dumps(
            {"text": "小苏目前只能理解文字消息哦，请把问题用文字发给我～"},
            ensure_ascii=False))
        return

    question = feishu_bot.extract_question(content, message.mentions)
    if not question:
        # 群里只 @ 了机器人但没说话 → 轻提示
        if chat_type == "group":
            _send_reply(message_id, "text", json.dumps(
                {"text": "在的，有什么可以帮你？直接把问题发给我就行～"},
                ensure_ascii=False))
        return

    logger.info(
        f"收到消息 chat_type={chat_type} open_id={open_id} "
        f"chat_id={chat_id} question={question[:50]!r}"
    )

    from app.database import async_session_factory
    try:
        async with async_session_factory() as db:
            msg_type, reply_content = await feishu_bot.process_question(
                db, open_id, chat_id, question
            )
        _send_reply(message_id, msg_type, reply_content)
        logger.info(f"已回复 message_id={message_id} msg_type={msg_type}")
    except Exception as e:
        # 全局兜底：后端异常 / LLM 超时 → 友好文案
        logger.exception(f"处理消息异常 message_id={message_id}: {e}")
        try:
            _send_reply(message_id, "text", json.dumps(
                {"text": feishu_bot.FALLBACK_TEXT}, ensure_ascii=False))
        except Exception as send_err:
            logger.error(f"兜底回复也失败: {send_err}")


def _on_message_receive(data: P2ImMessageReceiveV1) -> None:
    """lark SDK 事件回调（运行在 SDK 子线程）。投递到专用事件循环执行。"""
    try:
        future = asyncio.run_coroutine_threadsafe(_handle_message_async(data), _loop)
        future.result(timeout=180)  # 等待处理完成，超时会抛异常被下方捕获
    except Exception as e:
        logger.exception(f"事件处理失败: {e}")


def main() -> None:
    if not settings.FEISHU_APP_ID or not settings.FEISHU_APP_SECRET:
        logger.error(
            "缺少飞书凭据：请在 backend/.env 配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET"
        )
        raise SystemExit(1)

    # 启动专用事件循环线程
    threading.Thread(target=_run_loop, name="bot-asyncio-loop", daemon=True).start()

    # 启动前确保数据库结构最新（含 conversations.open_id/chat_id 补列）
    try:
        from app.database import ensure_schema
        asyncio.run_coroutine_threadsafe(ensure_schema(), _loop).result(timeout=30)
        logger.info("数据库结构检查完成")
    except Exception as e:
        logger.warning(f"数据库结构检查失败（机器人继续启动）: {e}")

    # 装配事件分发器：订阅 im.message.receive_v1
    event_handler = lark.EventDispatcherHandler.builder(
        settings.FEISHU_ENCRYPT_KEY,
        settings.FEISHU_VERIFICATION_TOKEN,
    ).register_p2_im_message_receive_v1(_on_message_receive).build()

    # 长连接客户端（自动重连）
    ws_client = lark.ws.Client(
        settings.FEISHU_APP_ID,
        settings.FEISHU_APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
        auto_reconnect=True,
    )

    logger.info("🤖 小苏飞书机器人启动中（长连接模式）...")
    logger.info(f"   默认知识库 ID: {settings.FEISHU_DEFAULT_KB_ID or '自动选择第一个'}")
    ws_client.start()  # 阻塞，内部维持 WebSocket 长连接


if __name__ == "__main__":
    main()
