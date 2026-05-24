"""
smart_routing.py — 智能模型路由

借鉴 hermes-agent 的 smart_model_routing.py 设计，提供：
- 根据消息复杂度自动选择模型
- 简单问题走便宜模型，节省成本
- 复杂问题（代码、调试、分析）走强大模型

移植策略：简化 hermes-agent 的实现，适配 All-Agent Manager 的
ModelProvider 架构，支持配置多个供应商的廉价/强力模型组合。
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ── 复杂度关键词 ──

_COMPLEX_KEYWORDS = {
    # 代码相关
    "代码", "编程", "写代码", "python", "javascript", "typescript", "go", "rust",
    "bug", "调试", "debug", "实现", "接口", "api", "脚本", "script",
    "重构", "refactor", "架构", "architecture", "设计模式",
    # 分析相关
    "分析", "analyze", "研究", "research", "对比", "compare", "评估", "evaluate",
    "报告", "report", "总结", "summary", "调研", "survey",
    # 技术相关
    "数据库", "database", "sql", "docker", "kubernetes", "部署", "deploy",
    "测试", "test", "pytest", "性能", "performance", "优化", "optimize",
    # 复杂任务
    "计划", "plan", "方案", "设计", "design", "review", "审查",
    "翻译", "translate",  # 长文本翻译需要强力模型
}

_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_CODE_BLOCK_RE = re.compile(r"```|`[^`]+`")


@dataclass
class RoutingDecision:
    """路由决策结果"""
    use_cheap_model: bool
    reason: str
    cheap_provider_id: str = ""
    cheap_model: str = ""


def analyze_message_complexity(message: str) -> float:
    """分析消息复杂度，返回 0.0-1.0 的分数

    0.0 = 非常简单（问候、简短问题）
    1.0 = 非常复杂（代码、分析、长文本）
    """
    if not message:
        return 0.0

    text = message.strip()
    score = 0.0

    # 长度因素
    char_count = len(text)
    word_count = len(text.split())
    newline_count = text.count("\n")

    if char_count > 500:
        score += 0.3
    elif char_count > 200:
        score += 0.15
    elif char_count > 100:
        score += 0.05

    if word_count > 100:
        score += 0.2
    elif word_count > 50:
        score += 0.1

    if newline_count > 5:
        score += 0.15
    elif newline_count > 2:
        score += 0.05

    # 代码块
    if "```" in text:
        score += 0.3
    elif "`" in text:
        score += 0.1

    # URL
    if _URL_RE.search(text):
        score += 0.1

    # 复杂度关键词
    lowered = text.lower()
    words = set(re.findall(r'[\w一-鿿]+', lowered))
    complex_matches = words & _COMPLEX_KEYWORDS
    if complex_matches:
        score += min(0.3, len(complex_matches) * 0.1)

    return min(1.0, score)


def should_use_cheap_model(
    message: str,
    routing_config: Optional[dict] = None,
) -> RoutingDecision:
    """决定是否使用廉价模型

    Args:
        message: 用户消息
        routing_config: 路由配置字典，包含：
            - enabled: bool 是否启用智能路由
            - cheap_provider_id: str 廉价供应商 ID
            - cheap_model: str 廉价模型名称
            - complexity_threshold: float 复杂度阈值（默认 0.3）
            - max_simple_chars: int 简单消息的最大字符数（默认 160）
            - max_simple_words: int 简单消息的最大词数（默认 28）

    Returns:
        RoutingDecision
    """
    cfg = routing_config or {}
    if not cfg.get("enabled", False):
        return RoutingDecision(use_cheap_model=False, reason="智能路由未启用")

    cheap_provider_id = cfg.get("cheap_provider_id", "")
    cheap_model = cfg.get("cheap_model", "")
    if not cheap_provider_id or not cheap_model:
        return RoutingDecision(use_cheap_model=False, reason="未配置廉价模型")

    text = (message or "").strip()
    if not text:
        return RoutingDecision(use_cheap_model=False, reason="空消息")

    # 快速过滤
    max_chars = cfg.get("max_simple_chars", 160)
    max_words = cfg.get("max_simple_words", 28)
    complexity_threshold = cfg.get("complexity_threshold", 0.3)

    if len(text) > max_chars:
        return RoutingDecision(use_cheap_model=False, reason=f"消息过长 ({len(text)} > {max_chars})")

    if len(text.split()) > max_words:
        return RoutingDecision(use_cheap_model=False, reason=f"词数过多")

    if text.count("\n") > 1:
        return RoutingDecision(use_cheap_model=False, reason="多行消息")

    if "```" in text or "`" in text:
        return RoutingDecision(use_cheap_model=False, reason="包含代码")

    if _URL_RE.search(text):
        return RoutingDecision(use_cheap_model=False, reason="包含 URL")

    # 复杂度分析
    complexity = analyze_message_complexity(text)
    if complexity >= complexity_threshold:
        return RoutingDecision(
            use_cheap_model=False,
            reason=f"复杂度过高 ({complexity:.2f} >= {complexity_threshold})",
        )

    logger.info("智能路由：简单消息 (%.2f 复杂度) -> %s/%s", complexity, cheap_provider_id, cheap_model)
    return RoutingDecision(
        use_cheap_model=True,
        reason=f"简单消息 (复杂度 {complexity:.2f})",
        cheap_provider_id=cheap_provider_id,
        cheap_model=cheap_model,
    )


# ── 路由配置预设 ──

DEFAULT_ROUTING_CONFIG = {
    "enabled": False,
    "cheap_provider_id": "",      # 廉价供应商 ID
    "cheap_model": "",            # 廉价模型名称
    "complexity_threshold": 0.3,  # 复杂度阈值
    "max_simple_chars": 160,      # 简单消息最大字符数
    "max_simple_words": 28,       # 简单消息最大词数
}

# 推荐的廉价模型组合
RECOMMENDED_CHEAP_MODELS = {
    "deepseek": {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "description": "DeepSeek Chat — 性价比极高的中文模型",
    },
    "dashscope_turbo": {
        "provider": "dashscope",
        "model": "qwen-turbo",
        "description": "Qwen Turbo — 阿里通义千问轻量版",
    },
    "siliconflow": {
        "provider": "siliconflow",
        "model": "deepseek-ai/DeepSeek-V3",
        "description": "SiliconFlow 上的 DeepSeek V3",
    },
    "groq": {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "description": "Groq Llama 3.3 — 超快推理",
    },
    "ollama_local": {
        "provider": "ollama",
        "model": "qwen2.5:7b",
        "description": "本地 Ollama — 零成本但需要本地 GPU",
    },
}
