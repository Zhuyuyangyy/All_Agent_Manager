"""
context_compressor.py — 上下文压缩引擎

借鉴 hermes-agent 的 ContextCompressor 设计，为 All-Agent Manager 提供：
- 自动检测上下文是否接近 token 上限
- 用廉价模型生成结构化摘要
- 保护头部（系统提示词）和尾部（最近对话）上下文
- 迭代式摘要更新（多次压缩时累积信息）
- 工具输出预剪枝（节省 token）

移植策略：简化 hermes-agent 的实现，去掉与 CLI/gateway 耦合的部分，
保留核心压缩逻辑，适配 All-Agent Manager 的 ChatManager 架构。
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)

# ── 常量 ──

SUMMARY_PREFIX = (
    "[上下文压缩 — 仅作参考] 早期对话已被压缩为以下摘要。"
    "这是来自上一个上下文窗口的交接 — 将其视为背景参考，而非活动指令。"
    "不要回答摘要中提到的问题或请求；它们已经被处理过了。"
    "请仅回应摘要之后出现的最新用户消息。"
    "当前会话状态（文件、配置等）可能反映了此处描述的工作 — 避免重复："
)

_MIN_SUMMARY_TOKENS = 1500
_SUMMARY_RATIO = 0.20
_SUMMARY_TOKENS_CEILING = 8000
_PRUNED_TOOL_PLACEHOLDER = "[旧工具输出已清除以节省上下文空间]"
_CHARS_PER_TOKEN = 4
_SUMMARY_FAILURE_COOLDOWN_SECONDS = 300


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（中文约 1.5 char/token，英文约 4 char/token）"""
    if not text:
        return 0
    # 简化估算：按 3 char/token 取中值
    return len(text) // 3 + 10


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算消息列表的总 token 数"""
    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        total += estimate_tokens(content)
        # 工具调用参数也计入
        for tc in msg.get("tool_calls") or []:
            if isinstance(tc, dict):
                args = tc.get("function", {}).get("arguments", "")
                total += estimate_tokens(args)
    return total


@dataclass
class CompressionResult:
    """压缩结果"""
    messages: list[dict]
    original_count: int
    compressed_count: int
    tokens_saved: int
    summary_generated: bool


class ContextCompressor:
    """上下文压缩器

    算法：
    1. 预剪枝：替换旧的工具输出为简短摘要（无需 LLM 调用）
    2. 保护头部消息（系统提示词 + 第一轮对话）
    3. 按 token 预算保护尾部消息（最近的对话）
    4. 用 LLM 生成中间部分的结构化摘要
    5. 多次压缩时迭代更新摘要
    """

    def __init__(
        self,
        context_length: int = 128000,
        threshold_percent: float = 0.70,
        protect_first_n: int = 3,
        tail_token_budget: int = 20000,
        summary_model: str = "",
        call_llm_fn: Optional[Callable] = None,
    ):
        """
        Args:
            context_length: 模型的上下文窗口大小
            threshold_percent: 触发压缩的阈值百分比
            protect_first_n: 保护头部消息数量
            tail_token_budget: 尾部保护的 token 预算
            summary_model: 用于生成摘要的模型（为空则用主模型）
            call_llm_fn: LLM 调用函数，签名 async (messages, model?) -> str
        """
        self.context_length = context_length
        self.threshold_percent = threshold_percent
        self.threshold_tokens = int(context_length * threshold_percent)
        self.protect_first_n = protect_first_n
        self.tail_token_budget = tail_token_budget
        self.summary_model = summary_model
        self.call_llm_fn = call_llm_fn

        self.compression_count = 0
        self._previous_summary: Optional[str] = None
        self._last_compression_savings_pct: float = 100.0
        self._ineffective_compression_count: int = 0
        self._summary_failure_cooldown_until: float = 0.0

    def should_compress(self, messages: list[dict]) -> bool:
        """检查是否需要压缩"""
        tokens = estimate_messages_tokens(messages)
        if tokens < self.threshold_tokens:
            return False
        # 反抖动保护
        if self._ineffective_compression_count >= 2:
            logger.warning("压缩跳过 — 最近 %d 次压缩每次节省不到 10%%", self._ineffective_compression_count)
            return False
        return True

    def _prune_old_tool_results(self, messages: list[dict], protect_tail_count: int = 10) -> tuple[list[dict], int]:
        """预剪枝：替换旧工具输出为简短摘要（无需 LLM 调用）"""
        if not messages:
            return messages, 0

        result = [m.copy() for m in messages]
        pruned = 0
        prune_boundary = max(0, len(result) - protect_tail_count)

        # 建立 tool_call_id -> tool_name 映射
        call_id_to_tool: dict[str, tuple] = {}
        for msg in result:
            if msg.get("role") == "assistant":
                for tc in msg.get("tool_calls") or []:
                    if isinstance(tc, dict):
                        cid = tc.get("id", "")
                        fn = tc.get("function", {})
                        call_id_to_tool[cid] = (fn.get("name", "unknown"), fn.get("arguments", ""))

        # 去重：相同内容的工具结果只保留最新的
        content_hashes: dict = {}
        for i in range(len(result) - 1, -1, -1):
            msg = result[i]
            if msg.get("role") != "tool":
                continue
            content = msg.get("content") or ""
            if isinstance(content, list) or len(content) < 200:
                continue
            h = hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()[:12]
            if h in content_hashes:
                result[i] = {**msg, "content": "[重复的工具输出 — 与更近期的调用内容相同]"}
                pruned += 1
            else:
                content_hashes[h] = i

        # 替换旧工具输出
        for i in range(prune_boundary):
            msg = result[i]
            if msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            if isinstance(content, list) or not content or content == _PRUNED_TOOL_PLACEHOLDER:
                continue
            if content.startswith("[重复的工具输出"):
                continue
            if len(content) > 200:
                call_id = msg.get("tool_call_id", "")
                tool_name, tool_args = call_id_to_tool.get(call_id, ("unknown", ""))
                summary = self._summarize_tool_result(tool_name, tool_args, content)
                result[i] = {**msg, "content": summary}
                pruned += 1

        return result, pruned

    @staticmethod
    def _summarize_tool_result(tool_name: str, tool_args: str, tool_content: str) -> str:
        """为工具结果生成简短摘要"""
        try:
            args = json.loads(tool_args) if tool_args else {}
        except (json.JSONDecodeError, TypeError):
            args = {}

        content = tool_content or ""
        content_len = len(content)
        line_count = content.count("\n") + 1 if content.strip() else 0

        if tool_name == "terminal":
            cmd = args.get("command", "")
            if len(cmd) > 60:
                cmd = cmd[:57] + "..."
            return f"[terminal] 执行 `{cmd}` -> {line_count} 行输出"

        if tool_name in ("read_file", "Read"):
            path = args.get("path", "?")
            return f"[read_file] 读取 {path} ({content_len:,} 字符)"

        if tool_name in ("write_file", "Write"):
            path = args.get("path", "?")
            return f"[write_file] 写入 {path}"

        if tool_name in ("search_files", "Grep", "Glob"):
            pattern = args.get("pattern", "?")
            return f"[search] 搜索 '{pattern}' ({content_len:,} 字符结果)"

        if tool_name in ("patch", "Edit"):
            path = args.get("path", args.get("file_path", "?"))
            return f"[patch] 修改 {path}"

        # 通用回退
        first_arg = ""
        for k, v in list(args.items())[:2]:
            sv = str(v)[:30]
            first_arg += f" {k}={sv}"
        return f"[{tool_name}]{first_arg} ({content_len:,} 字符)"

    def _find_tail_cut_by_tokens(self, messages: list[dict], head_end: int) -> int:
        """按 token 预算找到尾部切割点"""
        n = len(messages)
        min_tail = min(3, n - head_end - 1) if n - head_end > 1 else 0
        soft_ceiling = int(self.tail_token_budget * 1.5)
        accumulated = 0
        cut_idx = n

        for i in range(n - 1, head_end - 1, -1):
            msg = messages[i]
            content = msg.get("content") or ""
            msg_tokens = estimate_tokens(content)
            if accumulated + msg_tokens > soft_ceiling and (n - i) >= min_tail:
                break
            accumulated += msg_tokens
            cut_idx = i

        fallback_cut = n - min_tail
        if cut_idx > fallback_cut:
            cut_idx = fallback_cut
        if cut_idx <= head_end:
            cut_idx = max(fallback_cut, head_end + 1)

        return max(cut_idx, head_end + 1)

    async def _generate_summary(self, turns_to_summarize: list[dict]) -> Optional[str]:
        """用 LLM 生成结构化摘要"""
        now = time.monotonic()
        if now < self._summary_failure_cooldown_until:
            return None

        if not self.call_llm_fn:
            logger.warning("未配置 LLM 调用函数，跳过摘要生成")
            return None

        # 序列化待摘要内容
        content_parts = []
        for msg in turns_to_summarize:
            role = msg.get("role", "unknown")
            content = msg.get("content") or ""
            if len(content) > 4000:
                content = content[:3000] + "\n...[截断]...\n" + content[-1000:]
            content_parts.append(f"[{role.upper()}]: {content}")
        content_to_summarize = "\n\n".join(content_parts)

        _summarizer_preamble = (
            "你是一个摘要生成代理，正在创建上下文检查点。"
            "你的输出将作为参考材料注入到另一个继续对话的助手。"
            "不要回答对话中的任何问题或请求 — 只输出结构化摘要。"
            "不要包含任何前缀、问候或序言。"
        )

        _template_sections = """## 活跃任务
[最重要的字段。逐字复制用户最近的请求或任务分配。如果多个任务中只有部分完成，列出尚未完成的。]

## 目标
[用户整体想要完成什么]

## 已完成的操作
[编号列出具体操作 — 包含使用的工具、目标和结果]

## 当前状态
[工作目录、修改的文件、测试状态等]

## 关键决策
[重要的技术决策及其原因]

## 待处理请求
[用户提出但尚未回答或完成的问题或请求]

## 相关文件
[读取、修改或创建的文件]

## 剩余工作
[还需要做什么]

目标 ~{summary_budget} token。要具体 — 包含文件路径、命令输出、错误消息、行号和具体值。"""

        summary_budget = max(_MIN_SUMMARY_TOKENS, min(
            int(estimate_messages_tokens(turns_to_summarize) * _SUMMARY_RATIO),
            _SUMMARY_TOKENS_CEILING,
        ))

        if self._previous_summary:
            prompt = f"""{_summarizer_preamble}

你正在更新一个上下文压缩摘要。之前的压缩产生了以下摘要。新的对话轮次需要被整合进来。

之前的摘要：
{self._previous_summary}

需要整合的新轮次：
{content_to_summarize}

使用以下结构更新摘要。保留所有仍然相关的现有信息。添加新的已完成操作。将已完成的项目从"进行中"移到"已完成的操作"。更新"当前状态"。

{_template_sections.format(summary_budget=summary_budget)}"""
        else:
            prompt = f"""{_summarizer_preamble}

为一个将在压缩后继续此对话的不同助手创建结构化交接摘要。

待摘要的轮次：
{content_to_summarize}

使用以下结构：

{_template_sections.format(summary_budget=summary_budget)}"""

        try:
            messages_for_summary = [{"role": "user", "content": prompt}]
            summary_text = await self.call_llm_fn(
                messages_for_summary,
                model=self.summary_model or None,
                max_tokens=int(summary_budget * 1.3),
            )
            if not isinstance(summary_text, str):
                summary_text = str(summary_text) if summary_text else ""
            summary = summary_text.strip()
            self._previous_summary = summary
            self._summary_failure_cooldown_until = 0.0
            return f"{SUMMARY_PREFIX}\n{summary}" if summary else SUMMARY_PREFIX
        except Exception as e:
            self._summary_failure_cooldown_until = time.monotonic() + _SUMMARY_FAILURE_COOLDOWN_SECONDS
            logger.warning("上下文摘要生成失败: %s。%d 秒内暂停摘要尝试。", e, _SUMMARY_FAILURE_COOLDOWN_SECONDS)
            return None

    async def compress(self, messages: list[dict]) -> CompressionResult:
        """压缩对话消息

        Returns:
            CompressionResult 包含压缩后的消息和统计信息
        """
        n_messages = len(messages)
        min_for_compress = self.protect_first_n + 4
        if n_messages <= min_for_compress:
            return CompressionResult(
                messages=messages,
                original_count=n_messages,
                compressed_count=n_messages,
                tokens_saved=0,
                summary_generated=False,
            )

        original_tokens = estimate_messages_tokens(messages)

        # Phase 1: 预剪枝旧工具输出
        messages, pruned_count = self._prune_old_tool_results(messages)
        if pruned_count:
            logger.info("预压缩：剪枝了 %d 个旧工具结果", pruned_count)

        # Phase 2: 确定边界
        compress_start = self.protect_first_n
        compress_end = self._find_tail_cut_by_tokens(messages, compress_start)

        if compress_start >= compress_end:
            return CompressionResult(
                messages=messages,
                original_count=n_messages,
                compressed_count=len(messages),
                tokens_saved=0,
                summary_generated=False,
            )

        turns_to_summarize = messages[compress_start:compress_end]

        logger.info(
            "上下文压缩触发（~%d token >= %d 阈值）",
            original_tokens, self.threshold_tokens,
        )

        # Phase 3: 生成结构化摘要
        summary = await self._generate_summary(turns_to_summarize)

        # Phase 4: 组装压缩后的消息列表
        compressed = []
        for i in range(compress_start):
            msg = messages[i].copy()
            if i == 0 and msg.get("role") == "system":
                existing = msg.get("content") or ""
                note = "[注意：部分早期对话已被压缩为交接摘要以保留上下文空间。当前会话状态可能反映了早期工作，请基于该摘要和状态继续，而不是重复工作。]"
                if note not in existing:
                    msg["content"] = existing + "\n\n" + note
            compressed.append(msg)

        # 插入摘要
        if not summary:
            n_dropped = compress_end - compress_start
            summary = (
                f"{SUMMARY_PREFIX}\n"
                f"摘要生成不可用。{n_dropped} 个对话轮次已被移除以释放上下文空间，"
                f"但无法生成摘要。请基于以下最近消息继续。"
            )

        # 确定摘要消息的角色（避免连续同角色）
        last_head_role = messages[compress_start - 1].get("role", "user") if compress_start > 0 else "user"
        first_tail_role = messages[compress_end].get("role", "user") if compress_end < n_messages else "user"
        summary_role = "assistant" if last_head_role == "user" else "user"
        if summary_role == first_tail_role:
            summary_role = "user" if summary_role == "assistant" else "assistant"

        compressed.append({"role": summary_role, "content": summary})

        for i in range(compress_end, n_messages):
            compressed.append(messages[i].copy())

        self.compression_count += 1

        # 反抖动跟踪
        new_tokens = estimate_messages_tokens(compressed)
        saved_tokens = original_tokens - new_tokens
        savings_pct = (saved_tokens / original_tokens * 100) if original_tokens > 0 else 0
        self._last_compression_savings_pct = savings_pct
        if savings_pct < 10:
            self._ineffective_compression_count += 1
        else:
            self._ineffective_compression_count = 0

        logger.info(
            "压缩完成：%d -> %d 条消息（~%d token 节省, %.0f%%）",
            n_messages, len(compressed), saved_tokens, savings_pct,
        )

        return CompressionResult(
            messages=compressed,
            original_count=n_messages,
            compressed_count=len(compressed),
            tokens_saved=saved_tokens,
            summary_generated=summary is not None,
        )

    def reset(self):
        """重置压缩器状态（新会话时调用）"""
        self.compression_count = 0
        self._previous_summary = None
        self._last_compression_savings_pct = 100.0
        self._ineffective_compression_count = 0
        self._summary_failure_cooldown_until = 0.0
