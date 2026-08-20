"""Isolated, tool-free generation of structured conversation summaries."""

from __future__ import annotations

from typing import Optional

from flickcode.context.models import SummaryResult
from flickcode.providers.base import BaseProvider, Message


SUMMARY_SECTION_HEADINGS = (
    "用户目标与明确约束",
    "已完成的工作",
    "关键决策与理由",
    "当前状态、未完成事项与阻塞点",
    "涉及的文件、路径与重要细节",
    "后续建议或下一步",
)

SUMMARY_SYSTEM_PROMPT = """你是 FlickCode 的上下文摘要器。
你只能根据输入的历史文本生成摘要，禁止调用任何工具。
先在内部完成分析草稿，再只输出正式摘要；不要输出草稿。
草稿不得写入会话、文件或最终摘要。
不得补写输入中不存在的代码细节；不确定内容必须标注“不确定”。
用户目标、约束、否定条件和明确决策应尽量保留原文；不要把它们改写成
未经证实的新结论。

正式摘要必须严格包含以下部分，并使用二级 Markdown 标题：
## 用户目标与明确约束
## 已完成的工作
## 关键决策与理由
## 当前状态、未完成事项与阻塞点
## 涉及的文件、路径与重要细节
## 后续建议或下一步
"""


def serialize_history(messages: list[Message]) -> str:
    """Serialize internal history safely for an isolated summary request."""
    call_names: dict[str, str] = {}
    blocks: list[str] = []
    for index, message in enumerate(messages, start=1):
        if message.role == "assistant":
            for call in message.tool_calls:
                call_id = str(call.get("id", ""))
                if call_id:
                    call_names[call_id] = str(call.get("name", "unknown"))

        header = f"[message {index}][{message.role}]"
        if message.role == "tool":
            name = call_names.get(message.tool_call_id, "unknown")
            header = (
                f"[message {index}][tool name={name} "
                f"id={message.tool_call_id or 'unknown'}]"
            )
        elif message.role == "assistant" and message.tool_calls:
            names = ", ".join(
                str(call.get("name", "unknown")) for call in message.tool_calls
            )
            header += f"[tool_calls={names}]"

        blocks.append(f"{header}\n{message.content}")
    return "\n\n".join(blocks)


def has_required_sections(content: str) -> bool:
    """Return whether a response follows the stable summary structure."""
    return all(f"## {heading}" in content for heading in SUMMARY_SECTION_HEADINGS)


class SummaryClient:
    """Call a provider directly without tools or ContextManager recursion."""

    def __init__(self, provider: BaseProvider):
        self.provider = provider

    def summarize(
        self,
        history_text: str,
        *,
        system_prompt: str = SUMMARY_SYSTEM_PROMPT,
    ) -> SummaryResult:
        """Generate one validated formal summary from serialized history."""
        parts: list[str] = []
        done = False
        try:
            for event in self.provider.stream_chat(
                [Message(role="user", content=history_text)],
                thinking=False,
                tools=None,
                system=system_prompt,
            ):
                if event.type == "text":
                    parts.append(event.content)
                elif event.type == "error":
                    return SummaryResult(error=event.content)
                elif event.type == "done":
                    done = True
        except Exception as exc:
            return SummaryResult(error=f"Summary request error: {exc}")

        content = "".join(parts).strip()
        if not done:
            return SummaryResult(error="Summary provider ended without a done event.")
        if not content:
            return SummaryResult(error="Summary provider returned no text.")
        if not has_required_sections(content):
            return SummaryResult(
                error="Summary response did not contain all required sections."
            )
        return SummaryResult(content=content, success=True)
