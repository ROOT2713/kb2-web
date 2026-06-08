"""LLM generation service — chat completion via DeepSeek / SkillClaw.

Ported from: kb-web server.py deepseek_chat() L1250-L1303
"""

from typing import List, Dict

from app.config import settings


async def chat(messages: List[Dict], stream: bool = False, max_retries: int = 3) -> str:
    """
    Send chat completion request to LLM.
    Supports streaming (SSE) and non-streaming modes.
    """
    # TODO: Port from kb-web server.py deepseek_chat()
    raise NotImplementedError


async def stream_chat(messages: List[Dict]):
    """Streaming chat — yields chunks via SSE."""
    # TODO: Port streaming logic
    raise NotImplementedError
