"""pytest 公共 fixtures"""
import sys
import os
import types
import pytest

# 确保 backend 目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ---- ragas 兼容（langchain-community 0.4.x 已移除 vertexai 模块） ----
# ragas 0.4.3 的 llms/base.py 仍硬导入 langchain_community.chat_models.vertexai.ChatVertexAI，
# 但 langchain-community 0.4.2（sunset 版）已删除该模块，导致 import ragas 直接崩溃。
# 本项目仅用 ragas 的 Ollama/OpenAI 适配器；ChatVertexAI 只出现在 base.py 的
# MULTIPLE_COMPLETION_SUPPORTED isinstance 列表中，注入 stub 类（永远不匹配真实 LLM 实例）
# 即可让 ragas 正常导入，且不影响任何运行时类型判断。
if "langchain_community.chat_models.vertexai" not in sys.modules:
    _stub_vertexai = types.ModuleType("langchain_community.chat_models.vertexai")
    _stub_vertexai.ChatVertexAI = type("ChatVertexAI", (), {})
    sys.modules["langchain_community.chat_models.vertexai"] = _stub_vertexai
