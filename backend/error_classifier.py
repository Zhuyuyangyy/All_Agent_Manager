"""
error_classifier.py — API 错误分类器与智能重试

借鉴 hermes-agent 的 error_classifier.py 设计，提供：
- 结构化错误分类（认证、限流、上下文溢出、服务器错误等）
- 智能恢复策略（重试、压缩上下文、切换模型、放弃）
- 抖动退避算法（防止并发重试风暴）

移植策略：简化 hermes-agent 的实现，去掉 provider-specific 的特殊处理
（如 Anthropic thinking signature），保留核心分类逻辑。
"""

import enum
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── 错误分类枚举 ──

class FailoverReason(enum.Enum):
    """API 调用失败原因 — 决定恢复策略"""
    auth = "auth"                          # 认证失败 (401/403)
    billing = "billing"                    # 额度耗尽 (402)
    rate_limit = "rate_limit"              # 限流 (429)
    overloaded = "overloaded"              # 服务过载 (503/529)
    server_error = "server_error"          # 服务器错误 (500/502)
    timeout = "timeout"                    # 超时
    context_overflow = "context_overflow"  # 上下文溢出
    model_not_found = "model_not_found"    # 模型不存在 (404)
    format_error = "format_error"          # 请求格式错误 (400)
    unknown = "unknown"                    # 未知错误


@dataclass
class ClassifiedError:
    """结构化错误分类结果"""
    reason: FailoverReason
    status_code: Optional[int] = None
    message: str = ""
    retryable: bool = True
    should_compress: bool = False
    should_fallback: bool = False
    retry_after_seconds: float = 0.0


# ── 模式匹配列表 ──

_BILLING_PATTERNS = [
    "insufficient credits", "insufficient_quota", "credit balance",
    "credits have been exhausted", "top up your credits",
    "payment required", "billing hard limit", "exceeded your current quota",
    "account is deactivated", "额度不足", "余额不足",
]

_RATE_LIMIT_PATTERNS = [
    "rate limit", "rate_limit", "too many requests", "throttled",
    "requests per minute", "tokens per minute", "requests per day",
    "try again in", "please retry after", "resource_exhausted",
    "请求频率", "限流", "请稍后再试",
]

_CONTEXT_OVERFLOW_PATTERNS = [
    "context length", "context size", "maximum context", "token limit",
    "too many tokens", "reduce the length", "exceeds the limit",
    "context window", "prompt is too long", "prompt exceeds max length",
    "maximum number of tokens", "上下文长度", "超过最大长度",
    "context length exceeded", "max_model_len",
]

_MODEL_NOT_FOUND_PATTERNS = [
    "is not a valid model", "invalid model", "model not found",
    "model_not_found", "does not exist", "no such model",
    "unknown model", "unsupported model",
]

_AUTH_PATTERNS = [
    "invalid api key", "invalid_api_key", "authentication",
    "unauthorized", "forbidden", "invalid token", "token expired",
    "access denied", "认证失败", "无效的 API",
]

_TRANSPORT_ERROR_TYPES = frozenset({
    "ReadTimeout", "ConnectTimeout", "PoolTimeout",
    "ConnectError", "ConnectionError", "ConnectionResetError",
    "TimeoutError", "ReadError", "ServerDisconnectedError",
})


# ── 抖动退避 ──

_jitter_counter = 0


def jittered_backoff(
    attempt: int,
    base_delay: float = 5.0,
    max_delay: float = 120.0,
    jitter_ratio: float = 0.5,
) -> float:
    """计算抖动指数退避延迟

    防止多个并发会话同时重试同一供应商（雷群效应）。
    """
    global _jitter_counter
    _jitter_counter += 1

    exponent = max(0, attempt - 1)
    if exponent >= 63 or base_delay <= 0:
        delay = max_delay
    else:
        delay = min(base_delay * (2 ** exponent), max_delay)

    seed = (time.time_ns() ^ (_jitter_counter * 0x9E3779B9)) & 0xFFFFFFFF
    rng = random.Random(seed)
    jitter = rng.uniform(0, jitter_ratio * delay)

    return delay + jitter


# ── 分类管道 ──

def classify_api_error(
    error: Exception,
    provider: str = "",
    model: str = "",
    approx_tokens: int = 0,
    context_length: int = 128000,
) -> ClassifiedError:
    """将 API 错误分类为结构化的恢复建议

    优先级管道：
    1. HTTP 状态码分类
    2. 错误码分类
    3. 消息模式匹配
    4. 传输错误启发式
    5. 兜底：未知（可重试）
    """
    status_code = _extract_status_code(error)
    error_type = type(error).__name__
    body = _extract_error_body(error)

    # 构建综合错误消息
    raw_msg = str(error).lower()
    body_msg = ""
    if isinstance(body, dict):
        err_obj = body.get("error", {})
        if isinstance(err_obj, dict):
            body_msg = (err_obj.get("message") or "").lower()
        if not body_msg:
            body_msg = (body.get("message") or "").lower()

    error_msg = raw_msg
    if body_msg and body_msg not in raw_msg:
        error_msg = raw_msg + " " + body_msg

    def _result(reason: FailoverReason, **overrides) -> ClassifiedError:
        defaults = {
            "reason": reason,
            "status_code": status_code,
            "message": _extract_message(error, body),
        }
        defaults.update(overrides)
        return ClassifiedError(**defaults)

    # ── 1. HTTP 状态码分类 ──

    if status_code is not None:
        if status_code == 401:
            return _result(FailoverReason.auth, retryable=False, should_fallback=True)

        if status_code == 403:
            return _result(FailoverReason.auth, retryable=False, should_fallback=True)

        if status_code == 402:
            return _classify_402(error_msg, _result)

        if status_code == 404:
            return _result(FailoverReason.model_not_found, retryable=False, should_fallback=True)

        if status_code == 429:
            retry_after = _extract_retry_after(error, body)
            return _result(
                FailoverReason.rate_limit,
                retryable=True,
                should_fallback=True,
                retry_after_seconds=retry_after,
            )

        if status_code == 400:
            if any(p in error_msg for p in _CONTEXT_OVERFLOW_PATTERNS):
                return _result(FailoverReason.context_overflow, retryable=True, should_compress=True)
            if any(p in error_msg for p in _MODEL_NOT_FOUND_PATTERNS):
                return _result(FailoverReason.model_not_found, retryable=False, should_fallback=True)
            # 大会话 + 模糊 400 → 可能是上下文溢出
            is_large = approx_tokens > context_length * 0.4 or approx_tokens > 80000
            if is_large and len(error_msg) < 50:
                return _result(FailoverReason.context_overflow, retryable=True, should_compress=True)
            return _result(FailoverReason.format_error, retryable=False, should_fallback=True)

        if status_code in (500, 502):
            return _result(FailoverReason.server_error, retryable=True)

        if status_code in (503, 529):
            return _result(FailoverReason.overloaded, retryable=True)

        if 400 <= status_code < 500:
            return _result(FailoverReason.format_error, retryable=False, should_fallback=True)

        if 500 <= status_code < 600:
            return _result(FailoverReason.server_error, retryable=True)

    # ── 2. 消息模式匹配 ──

    if any(p in error_msg for p in _BILLING_PATTERNS):
        return _result(FailoverReason.billing, retryable=False, should_fallback=True)

    if any(p in error_msg for p in _RATE_LIMIT_PATTERNS):
        retry_after = _extract_retry_after(error, body)
        return _result(FailoverReason.rate_limit, retryable=True, retry_after_seconds=retry_after)

    if any(p in error_msg for p in _CONTEXT_OVERFLOW_PATTERNS):
        return _result(FailoverReason.context_overflow, retryable=True, should_compress=True)

    if any(p in error_msg for p in _AUTH_PATTERNS):
        return _result(FailoverReason.auth, retryable=False, should_fallback=True)

    if any(p in error_msg for p in _MODEL_NOT_FOUND_PATTERNS):
        return _result(FailoverReason.model_not_found, retryable=False, should_fallback=True)

    # ── 3. 传输错误 ──

    if error_type in _TRANSPORT_ERROR_TYPES or isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return _result(FailoverReason.timeout, retryable=True)

    # ── 4. 兜底 ──

    return _result(FailoverReason.unknown, retryable=True)


def _classify_402(error_msg: str, result_fn) -> ClassifiedError:
    """区分 402：额度耗尽 vs 瞬时限流"""
    transient_signals = ["try again", "retry", "resets at", "reset in", "wait"]
    has_transient = any(s in error_msg for s in transient_signals)
    if has_transient:
        return result_fn(FailoverReason.rate_limit, retryable=True)
    return result_fn(FailoverReason.billing, retryable=False, should_fallback=True)


# ── 辅助函数 ──

def _extract_status_code(error: Exception) -> Optional[int]:
    """从错误中提取 HTTP 状态码"""
    current = error
    for _ in range(5):
        code = getattr(current, "status_code", None)
        if isinstance(code, int):
            return code
        code = getattr(current, "status", None)
        if isinstance(code, int) and 100 <= code < 600:
            return code
        cause = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
        if cause is None or cause is current:
            break
        current = cause
    return None


def _extract_error_body(error: Exception) -> dict:
    """从 SDK 异常中提取结构化错误体"""
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        return body
    response = getattr(error, "response", None)
    if response is not None:
        try:
            json_body = response.json()
            if isinstance(json_body, dict):
                return json_body
        except Exception:
            pass
    return {}


def _extract_message(error: Exception, body: dict) -> str:
    """提取最有用的错误消息"""
    if body:
        error_obj = body.get("error", {})
        if isinstance(error_obj, dict):
            msg = error_obj.get("message", "")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()[:500]
        msg = body.get("message", "")
        if isinstance(msg, str) and msg.strip():
            return msg.strip()[:500]
    return str(error)[:500]


def _extract_retry_after(error: Exception, body: dict) -> float:
    """提取 Retry-After 头的值（秒）"""
    # 从响应头
    response = getattr(error, "response", None)
    if response is not None:
        retry_after = response.headers.get("retry-after") or response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except (ValueError, TypeError):
                pass

    # 从错误体
    if isinstance(body, dict):
        ra = body.get("retry_after") or body.get("retry-after")
        if ra:
            try:
                return float(ra)
            except (ValueError, TypeError):
                pass

    # 从错误消息中提取 "try again in X seconds"
    msg = str(error).lower()
    import re
    match = re.search(r'(?:try again|retry)\s+(?:in\s+)?(\d+)\s*(?:s|sec|seconds?)', msg)
    if match:
        return float(match.group(1))

    return 0.0


# ── 重试执行器 ──

class RetryExecutor:
    """智能重试执行器

    根据错误分类自动决定重试策略。
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 5.0,
        max_delay: float = 120.0,
        on_compress: Optional[Any] = None,  # Callable[[], Awaitable[None]]
        on_fallback: Optional[Any] = None,  # Callable[[], Awaitable[str]]
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.on_compress = on_compress
        self.on_fallback = on_fallback

    async def execute_with_retry(
        self,
        call_fn,  # Callable[[], Awaitable[T]]
        context_tokens: int = 0,
        context_length: int = 128000,
    ) -> Any:
        """执行调用，自动重试和恢复

        Args:
            call_fn: 异步调用函数
            context_tokens: 当前上下文 token 数
            context_length: 模型上下文窗口大小

        Returns:
            调用结果

        Raises:
            最后一次尝试的异常
        """
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                return await call_fn()
            except Exception as e:
                last_error = e
                classified = classify_api_error(
                    e,
                    approx_tokens=context_tokens,
                    context_length=context_length,
                )

                logger.warning(
                    "API 调用失败 (尝试 %d/%d): %s — %s",
                    attempt + 1, self.max_retries + 1,
                    classified.reason.value, classified.message[:100],
                )

                # 不可重试 → 直接抛出
                if not classified.retryable:
                    # 但如果应该压缩上下文，先压缩再重试一次
                    if classified.should_compress and self.on_compress and attempt == 0:
                        logger.info("上下文溢出，尝试压缩后重试...")
                        await self.on_compress()
                        continue
                    raise

                # 应该压缩上下文
                if classified.should_compress and self.on_compress:
                    logger.info("上下文溢出，压缩后重试...")
                    await self.on_compress()
                    continue

                # 应该切换到备用模型
                if classified.should_fallback and self.on_fallback and attempt < self.max_retries:
                    logger.info("切换到备用模型...")
                    await self.on_fallback()
                    continue

                # 计算退避延迟
                if attempt < self.max_retries:
                    delay = classified.retry_after_seconds or jittered_backoff(
                        attempt + 1,
                        base_delay=self.base_delay,
                        max_delay=self.max_delay,
                    )
                    logger.info("等待 %.1f 秒后重试...", delay)
                    import asyncio
                    await asyncio.sleep(delay)

        raise last_error
