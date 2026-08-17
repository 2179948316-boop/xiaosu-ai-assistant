"""飞书机器人子包 - 将原 feishu_bot.py 按功能拆分

对外接口与拆之前的 feishu_bot.py 保持一致，方便 bot_service.py 和测试导入。
"""
# utils
from .utils import (
    FALLBACK_TEXT,
    _MEM_SEEN,
    _parse_sse,
    bot_mentioned,
    build_post_reply,
    build_text_reply,
    extract_question,
    is_duplicate,
    run_agent_and_collect,
)

# account
from .account import (
    _ACCOUNT_PENDING,
    handle_account_command,
    list_visible_kbs,
    parse_account_command,
    resolve_bound_user,
)

# binding
from .binding import (
    _find_kb_by_id,
    _find_kbs_by_name,
    _resolve_kb_id_only,
    get_or_create_conversation,
    handle_binding_command,
    parse_binding_command,
    set_binding,
)

# bot
from .bot import (
    ensure_feishu_user,
    process_question,
    resolve_kb_id,
)

# === 测试和旧代码兼容性：以下符号在拆分前是 feishu_bot.py 直引的第三方模块 ===
from app.services.agent_service import agent_chat_stream
from app.services.cache_service import _get_redis
from app.config import get_settings as _
settings = _()
from app.routers.auth import hash_password, verify_password

__all__ = [
    # utils
    "FALLBACK_TEXT",
    "_MEM_SEEN",
    "_parse_sse",
    "bot_mentioned",
    "build_post_reply",
    "build_text_reply",
    "extract_question",
    "is_duplicate",
    "run_agent_and_collect",
    # account
    "_ACCOUNT_PENDING",
    "handle_account_command",
    "list_visible_kbs",
    "parse_account_command",
    "resolve_bound_user",
    # binding
    "_find_kb_by_id",
    "_find_kbs_by_name",
    "_resolve_kb_id_only",
    "get_or_create_conversation",
    "handle_binding_command",
    "parse_binding_command",
    "set_binding",
    # bot
    "ensure_feishu_user",
    "process_question",
    "resolve_kb_id",
    # 兼容性符号
    "agent_chat_stream",
    "_get_redis",
    "settings",
    "hash_password",
    "verify_password",
]