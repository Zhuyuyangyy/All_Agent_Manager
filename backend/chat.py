"""
chat.py — 对话模块

支持多模型供应商配置，提供 AI 对话能力。
支持 iliya 人格和子 Agent 调度。
借鉴 OpenHanako 的 ProviderRegistry 设计：
  - 预置供应商（Ollama、OpenAI、DeepSeek、DashScope 等）
  - API 格式支持（openai-completions、anthropic-messages）
  - 每个供应商可配置多个模型
  - 连接验证

借鉴 hermes-agent 的高级特性：
  - 上下文压缩（ContextCompressor）：自动压缩长对话
  - 错误分类（ErrorClassifier）：智能重试和恢复
  - 智能模型路由（SmartRouting）：简单问题走便宜模型
"""

import json
import os
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# ── 导入 hermes-agent 借鉴的模块 ──
try:
    from backend.context_compressor import ContextCompressor, estimate_messages_tokens
    from backend.error_classifier import classify_api_error, jittered_backoff, RetryExecutor
    from backend.smart_routing import should_use_cheap_model, DEFAULT_ROUTING_CONFIG
    _HAS_ADVANCED_FEATURES = True
except ImportError:
    _HAS_ADVANCED_FEATURES = False
    logger.info("高级特性模块未找到，将以基础模式运行")


# ── 供应商预设（借鉴 OpenHanako provider-presets.ts）──

PROVIDER_PRESETS: dict[str, dict] = {
    "ollama": {
        "display_name": "Ollama (本地)",
        "api_base": "http://localhost:11434/v1",
        "api_format": "openai-completions",
        "local": True,
        "default_models": ["llama3", "qwen2.5", "deepseek-r1", "gemma2"],
    },
    "openai": {
        "display_name": "OpenAI",
        "api_base": "https://api.openai.com/v1",
        "api_format": "openai-completions",
        "default_models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo", "o1-preview", "o1-mini"],
    },
    "anthropic": {
        "display_name": "Anthropic",
        "api_base": "https://api.anthropic.com",
        "api_format": "anthropic-messages",
        "default_models": ["claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"],
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "api_base": "https://api.deepseek.com",
        "api_format": "openai-completions",
        "default_models": ["deepseek-chat", "deepseek-coder", "deepseek-reasoner"],
    },
    "dashscope": {
        "display_name": "DashScope (Qwen)",
        "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_format": "openai-completions",
        "default_models": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen-long"],
    },
    "moonshot": {
        "display_name": "Moonshot (Kimi)",
        "api_base": "https://api.moonshot.cn/v1",
        "api_format": "openai-completions",
        "default_models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
    },
    "zhipu": {
        "display_name": "Zhipu (GLM)",
        "api_base": "https://open.bigmodel.cn/api/paas/v4",
        "api_format": "openai-completions",
        "default_models": ["glm-4-plus", "glm-4-flash", "glm-4-air", "glm-4-long"],
    },
    "siliconflow": {
        "display_name": "SiliconFlow",
        "api_base": "https://api.siliconflow.cn/v1",
        "api_format": "openai-completions",
        "default_models": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-72B-Instruct"],
    },
    "groq": {
        "display_name": "Groq",
        "api_base": "https://api.groq.com/openai/v1",
        "api_format": "openai-completions",
        "default_models": ["llama-3.3-70b-versatile", "mixtral-8x7b-32768"],
    },
    "minimax": {
        "display_name": "MiniMax",
        "api_base": "https://api.minimaxi.com/anthropic",
        "api_format": "anthropic-messages",
        "default_models": ["MiniMax-Text-01", "MiniMax-M1"],
    },
    "volcengine": {
        "display_name": "Volcengine (豆包)",
        "api_base": "https://ark.cn-beijing.volces.com/api/v3",
        "api_format": "openai-completions",
        "default_models": ["doubao-pro-32k", "doubao-lite-32k"],
    },
}

API_FORMAT_OPTIONS = [
    {"value": "openai-completions", "label": "OpenAI Compatible"},
    {"value": "anthropic-messages", "label": "Anthropic Messages"},
    {"value": "ollama-chat", "label": "Ollama Native"},
]


# ── Agent 调度关键词 ──

AGENT_KEYWORDS = {
    "openclaw": ["代码", "编程", "写代码", "python", "javascript", "typescript", "go", "rust",
                 "bug", "调试", "debug", "实现", "接口", "api", "脚本", "script", "编程"],
    "openhanako": ["微信", "wechat", "文件", "file", "桌面", "desktop", "本地", "local",
                   "桥接", "bridge", "整理文件", "读取文件", "写入文件"],
    "hermes": ["研究", "research", "分析", "analyze", "总结", "summary", "调研", "survey",
               "报告", "report", "查资料", "查找", "对比", "评估", "整理信息"],
}


@dataclass
class ModelProvider:
    """模型供应商配置（借鉴 OpenHanako ProviderEntry）"""
    id: str
    name: str
    api_format: str = "openai-completions"  # openai-completions | anthropic-messages | ollama-chat
    api_key: str = ""
    api_base: str = ""
    models: list[str] = field(default_factory=list)   # 可用模型列表
    active_model: str = ""                             # 当前选中的模型
    temperature: float = 0.7
    max_tokens: int = 4096
    enabled: bool = True
    preset: str = ""                                   # 预设 ID（如 "openai", "deepseek"）
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "api_format": self.api_format,
            "api_key_masked": self.api_key[:8] + "..." if len(self.api_key) > 8 else ("***" if self.api_key else ""),
            "api_base": self.api_base,
            "models": self.models,
            "active_model": self.active_model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "enabled": self.enabled,
            "preset": self.preset,
            "created_at": self.created_at,
        }

    def to_full_dict(self) -> dict:
        """包含完整 API key 的字典（仅内部存储）"""
        d = self.to_dict()
        d["api_key"] = self.api_key
        d.pop("api_key_masked", None)
        return d


@dataclass
class ChatMessage:
    """聊天消息"""
    id: str
    role: str  # "user", "assistant", "system"
    content: str
    provider_id: str = ""
    model: str = ""
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    tokens_used: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "provider_id": self.provider_id,
            "model": self.model,
            "timestamp": self.timestamp,
            "tokens_used": self.tokens_used,
        }


class ChatManager:
    """对话管理器

    借鉴 hermes-agent 的高级特性：
    - 上下文压缩：当对话接近 token 上限时自动压缩
    - 错误分类：智能重试和恢复策略
    - 智能路由：简单问题走便宜模型，节省成本
    """

    def __init__(self, storage_dir: str | Path = "storage"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.providers_file = self.storage_dir / "model_providers.json"
        self.chat_history_file = self.storage_dir / "chat_history.json"
        self.routing_config_file = self.storage_dir / "routing_config.json"

        self._providers: dict[str, ModelProvider] = {}
        self._chat_history: list[ChatMessage] = []
        self._active_provider_id: str = ""

        # ── 高级特性组件 ──
        self._context_compressor: Optional[ContextCompressor] = None
        self._retry_executor: Optional[RetryExecutor] = None
        self._routing_config: dict = DEFAULT_ROUTING_CONFIG.copy() if _HAS_ADVANCED_FEATURES else {}

        self._load_providers()
        self._load_chat_history()
        self._load_routing_config()
        self._init_advanced_features()

    # ── 持久化 ──

    def _load_providers(self):
        if self.providers_file.exists():
            try:
                data = json.loads(self.providers_file.read_text(encoding="utf-8"))
                changed = False
                for p in data.get("providers", []):
                    # 兼容旧格式（provider_type → api_format）
                    if "provider_type" in p and "api_format" not in p:
                        p["api_format"] = p.pop("provider_type")
                    provider = ModelProvider(**{k: v for k, v in p.items() if k in ModelProvider.__dataclass_fields__})
                    # 自动修正：如果预设存在且 api_format 不匹配，用预设值
                    if provider.preset and provider.preset in PROVIDER_PRESETS:
                        expected = PROVIDER_PRESETS[provider.preset]["api_format"]
                        if provider.api_format != expected:
                            provider.api_format = expected
                            changed = True
                    self._providers[provider.id] = provider
                self._active_provider_id = data.get("active_provider_id", "")
                if changed:
                    self._save_providers()
            except Exception as e:
                logger.error(f"Failed to load providers: {e}")

    def _save_providers(self):
        data = {
            "providers": [p.to_full_dict() for p in self._providers.values()],
            "active_provider_id": self._active_provider_id,
        }
        self.providers_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def _load_chat_history(self):
        if self.chat_history_file.exists():
            try:
                data = json.loads(self.chat_history_file.read_text(encoding="utf-8"))
                for m in data.get("messages", []):
                    self._chat_history.append(ChatMessage(**m))
            except Exception as e:
                logger.error(f"Failed to load chat history: {e}")

    def _save_chat_history(self):
        recent = self._chat_history[-200:]
        data = {"messages": [m.to_dict() for m in recent]}
        self.chat_history_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    # ── 高级特性初始化（借鉴 hermes-agent）──

    def _load_routing_config(self):
        """加载智能路由配置"""
        if not _HAS_ADVANCED_FEATURES:
            return
        if self.routing_config_file.exists():
            try:
                data = json.loads(self.routing_config_file.read_text(encoding="utf-8"))
                self._routing_config = {**DEFAULT_ROUTING_CONFIG, **data}
            except Exception as e:
                logger.error(f"Failed to load routing config: {e}")

    def _save_routing_config(self):
        """保存智能路由配置"""
        if not _HAS_ADVANCED_FEATURES:
            return
        try:
            self.routing_config_file.write_text(
                json.dumps(self._routing_config, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            logger.error(f"Failed to save routing config: {e}")

    def _init_advanced_features(self):
        """初始化高级特性组件"""
        if not _HAS_ADVANCED_FEATURES:
            return

        try:
            # 初始化上下文压缩器
            self._context_compressor = ContextCompressor(
                context_length=128000,
                threshold_percent=0.70,
                protect_first_n=3,
                tail_token_budget=20000,
                call_llm_fn=self._call_llm_for_compression,
            )

            # 初始化重试执行器
            self._retry_executor = RetryExecutor(
                max_retries=2,
                base_delay=3.0,
                max_delay=30.0,
                on_compress=self._on_context_overflow,
            )

            logger.info("高级特性初始化完成：上下文压缩、错误分类、智能路由")
        except Exception as e:
            logger.warning(f"高级特性初始化失败（将以基础模式运行）: {e}")

    async def _call_llm_for_compression(self, messages: list[dict], model: str = None, max_tokens: int = 4000) -> str:
        """为上下文压缩调用 LLM（使用廉价模型）"""
        provider = self.get_active_provider()
        if not provider:
            raise RuntimeError("未配置模型供应商")

        # 如果指定了压缩模型，尝试找到对应的供应商
        compression_provider = provider
        if model:
            for p in self._providers.values():
                if model in p.models:
                    compression_provider = p
                    break

        # 使用较低的 max_tokens 节省成本
        original_max = compression_provider.max_tokens
        compression_provider.max_tokens = min(max_tokens, 4000)

        try:
            result = await self._call_model(compression_provider, messages)
            return result[0] if isinstance(result, tuple) else result
        finally:
            compression_provider.max_tokens = original_max

    async def _on_context_overflow(self):
        """上下文溢出时的回调：压缩对话历史"""
        if self._context_compressor and self._chat_history:
            messages = [{"role": m.role, "content": m.content} for m in self._chat_history]
            if self._context_compressor.should_compress(messages):
                result = await self._context_compressor.compress(messages)
                # 重建聊天历史
                self._chat_history.clear()
                for msg in result.messages:
                    self.add_message(
                        msg.get("role", "user"),
                        msg.get("content", ""),
                    )
                logger.info("上下文压缩完成：节省了约 %d token", result.tokens_saved)

    def get_routing_config(self) -> dict:
        """获取智能路由配置"""
        return self._routing_config.copy()

    def update_routing_config(self, **kwargs) -> dict:
        """更新智能路由配置"""
        for key, value in kwargs.items():
            if key in self._routing_config:
                self._routing_config[key] = value
        self._save_routing_config()
        return self._routing_config.copy()

    def get_recommended_cheap_models(self) -> dict:
        """获取推荐的廉价模型组合"""
        if _HAS_ADVANCED_FEATURES:
            from backend.smart_routing import RECOMMENDED_CHEAP_MODELS
            return RECOMMENDED_CHEAP_MODELS
        return {}

    # ── 供应商管理 ──

    def list_providers(self) -> list[dict]:
        return [p.to_dict() for p in self._providers.values()]

    def get_provider(self, provider_id: str) -> Optional[dict]:
        provider = self._providers.get(provider_id)
        return provider.to_dict() if provider else None

    def add_provider(self, name: str, api_format: str = "",
                     api_key: str = "", api_base: str = "",
                     models: list[str] | None = None, preset: str = "",
                     **kwargs) -> dict:
        """添加新供应商"""
        provider_id = f"provider_{uuid4().hex[:8]}"

        # 如果是预设，填充默认值
        if preset and preset in PROVIDER_PRESETS:
            ps = PROVIDER_PRESETS[preset]
            api_base = api_base or ps["api_base"]
            api_format = api_format or ps["api_format"]
            models = models or ps.get("default_models", [])

        provider = ModelProvider(
            id=provider_id,
            name=name,
            api_format=api_format,
            api_key=api_key,
            api_base=api_base,
            models=models or [],
            preset=preset,
            **kwargs
        )
        self._providers[provider_id] = provider
        self._save_providers()
        return provider.to_dict()

    def update_provider(self, provider_id: str, **kwargs) -> Optional[dict]:
        provider = self._providers.get(provider_id)
        if not provider:
            return None
        for key, value in kwargs.items():
            if hasattr(provider, key) and key != "id":
                # 空字符串不覆盖 api_key，避免误清空
                if key == "api_key" and value == "":
                    continue
                setattr(provider, key, value)
        self._save_providers()
        return provider.to_dict()

    def delete_provider(self, provider_id: str) -> bool:
        if provider_id in self._providers:
            del self._providers[provider_id]
            if self._active_provider_id == provider_id:
                self._active_provider_id = ""
            self._save_providers()
            return True
        return False

    def set_active_provider(self, provider_id: str) -> bool:
        if provider_id in self._providers or provider_id == "":
            self._active_provider_id = provider_id
            self._save_providers()
            return True
        return False

    def get_active_provider(self) -> Optional[ModelProvider]:
        if self._active_provider_id:
            return self._providers.get(self._active_provider_id)
        for p in self._providers.values():
            if p.enabled:
                return p
        return None

    def get_presets(self) -> dict:
        """获取所有预设供应商"""
        return PROVIDER_PRESETS

    def get_api_formats(self) -> list[dict]:
        """获取 API 格式选项"""
        return API_FORMAT_OPTIONS

    async def verify_connection(self, provider_id: str) -> dict:
        """验证供应商连接（借鉴 OpenHanako providers.js test）"""
        provider = self._providers.get(provider_id)
        if not provider:
            return {"ok": False, "error": "供应商不存在"}

        try:
            import httpx

            base = provider.api_base.rstrip("/")
            is_anthropic = provider.api_format == "anthropic-messages"
            is_ollama = provider.api_format == "ollama-chat"

            if is_ollama:
                ollama_base = provider.api_base.replace("/v1", "")
                url = f"{ollama_base}/api/tags"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                return {"ok": True}

            if is_anthropic:
                # Anthropic 兼容: POST /v1/messages 发送测试消息验证连通性
                # （借鉴 OpenHanako probeProvider：排除 401/403 即视为连通）
                url = f"{base}/v1/messages"
                headers = {
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01",
                }
                if provider.api_key:
                    headers["x-api-key"] = provider.api_key
                model = provider.active_model or (provider.models[0] if provider.models else "test")
                payload = {
                    "model": model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "."}],
                }
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    # 401/403：凭证问题
                    if resp.status_code in (401, 403):
                        return {"ok": False, "error": f"认证失败 (HTTP {resp.status_code})，请检查 API Key"}
                    # 其他状态码（包括 404、400 等）视为连通（服务端在线）
                    # 只要不是认证失败，就说明 API 地址和凭证是正确的
            else:
                # OpenAI 兼容: GET /models
                url = f"{base}/models"
                headers = {}
                if provider.api_key:
                    headers["Authorization"] = f"Bearer {provider.api_key}"
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code in (401, 403):
                        return {"ok": False, "error": f"认证失败 (HTTP {resp.status_code})，请检查 API Key"}
                    if resp.status_code == 404:
                        model = provider.active_model or "gpt-3.5-turbo"
                        url2 = f"{base}/chat/completions"
                        payload = {
                            "model": model,
                            "messages": [{"role": "user", "content": "Hi"}],
                            "max_tokens": 5,
                        }
                        async with httpx.AsyncClient(timeout=15.0) as client2:
                            resp2 = await client2.post(url2, json=payload, headers=headers)
                            resp2.raise_for_status()
                    else:
                        resp.raise_for_status()

            return {"ok": True}

        except httpx.ConnectError:
            return {"ok": False, "error": "无法连接到服务器，请检查 API 地址"}
        except httpx.TimeoutException:
            return {"ok": False, "error": "连接超时"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def fetch_models(self, provider_id: str) -> dict:
        """从供应商获取可用模型列表（借鉴 OpenHanako providers.js fetch-models）

        支持多种响应格式：
        - Anthropic 格式: { data: [{ id, display_name, max_input_tokens, max_tokens }] }
        - OpenAI 格式:   { data: [{ id, context_length, ... }] }
        - MiniMax 等:     { models: [...] } 或其他变体
        """
        provider = self._providers.get(provider_id)
        if not provider:
            return {"models": [], "error": "供应商不存在"}

        try:
            import httpx

            base = provider.api_base.rstrip("/")
            is_anthropic = provider.api_format == "anthropic-messages"
            is_ollama = provider.api_format == "ollama-chat"

            if is_ollama:
                # Ollama: GET /api/tags
                ollama_base = provider.api_base.replace("/v1", "")
                url = f"{ollama_base}/api/tags"
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.json()
                models = [{"id": m["name"], "name": m.get("name", m["name"]),
                           "context": None, "max_output": None}
                          for m in data.get("models", [])]
                return {"models": models}

            # Anthropic 兼容: GET /v1/models?limit=1000
            # OpenAI 兼容:   GET /models
            if is_anthropic:
                url = f"{base}/v1/models?limit=1000"
            else:
                url = f"{base}/models"

            # 构建认证头
            headers = {"Content-Type": "application/json"}
            if provider.api_key:
                if is_anthropic:
                    headers["x-api-key"] = provider.api_key
                    headers["anthropic-version"] = "2023-06-01"
                else:
                    headers["Authorization"] = f"Bearer {provider.api_key}"

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=headers)

                # 401/403：凭证问题
                if resp.status_code in (401, 403):
                    return {"models": [], "error": f"认证失败 (HTTP {resp.status_code})，请检查 API Key"}

                # 404：尝试备用端点，再回退到预设默认模型
                if resp.status_code == 404:
                    if is_anthropic:
                        # Anthropic 格式: 尝试 /models（去掉 /v1/ 前缀）
                        alt_url = f"{base}/models?limit=1000"
                    else:
                        # OpenAI 格式: 尝试 /v1/models
                        alt_url = f"{base}/v1/models"
                    logger.info(f"[fetch_models] 404 on {url}, trying alt: {alt_url}")
                    try:
                        alt_resp = await client.get(alt_url, headers=headers)
                        if alt_resp.status_code == 200:
                            alt_data = alt_resp.json()
                            raw_models = (
                                alt_data.get("data")
                                or alt_data.get("models")
                                or alt_data.get("list")
                                or alt_data.get("items")
                                or []
                            )
                            if raw_models:
                                models = []
                                for m in raw_models:
                                    if isinstance(m, str):
                                        models.append({"id": m, "name": m, "context": None, "max_output": None})
                                        continue
                                    mid = m.get("id", "") or m.get("name", "")
                                    if not mid:
                                        continue
                                    models.append({
                                        "id": mid,
                                        "name": m.get("display_name") or mid,
                                        "context": m.get("max_input_tokens") or m.get("context_length"),
                                        "max_output": m.get("max_tokens") or m.get("max_output_tokens"),
                                    })
                                if models:
                                    logger.info(f"[fetch_models] alt endpoint returned {len(models)} models")
                                    return {"models": models}
                    except Exception:
                        pass

                    # 回退到预设默认模型
                    if provider.preset and provider.preset in PROVIDER_PRESETS:
                        default_models = PROVIDER_PRESETS[provider.preset].get("default_models", [])
                        return {"models": [{"id": m, "name": m, "context": None, "max_output": None}
                                            for m in default_models]}
                    return {"models": [], "error": "该 API 不支持模型列表端点"}

                resp.raise_for_status()
                data = resp.json()

            # 归一化响应（借鉴 OpenHanako）
            # 支持多种响应格式：data.data, data.models, data.list, data.items
            raw_models = (
                data.get("data")       # OpenAI / Anthropic 标准格式
                or data.get("models")  # MiniMax / 部分国产供应商
                or data.get("list")    # 某些供应商
                or data.get("items")   # 某些供应商
                or []                  # 兜底
            )

            logger.info(f"[fetch_models] provider={provider.name} format={provider.api_format} "
                        f"url={url} raw_count={len(raw_models)} "
                        f"response_keys={list(data.keys())}")

            models = []
            for m in raw_models:
                # 支持字符串格式（["model1", "model2"]）
                if isinstance(m, str):
                    models.append({"id": m, "name": m, "context": None, "max_output": None})
                    continue
                # 对象格式
                mid = m.get("id", "")
                if not mid:
                    # 兼容 name 字段作为 id
                    mid = m.get("name", "")
                if not mid:
                    continue
                if is_anthropic:
                    models.append({
                        "id": mid,
                        "name": m.get("display_name") or mid,
                        "context": m.get("max_input_tokens"),
                        "max_output": m.get("max_tokens"),
                    })
                else:
                    models.append({
                        "id": mid,
                        "name": m.get("display_name") or mid,
                        "context": m.get("context_length") or m.get("context_window")
                                  or m.get("max_context_length") or m.get("max_input_tokens"),
                        "max_output": m.get("max_completion_tokens") or m.get("max_output_tokens")
                                      or m.get("max_tokens"),
                    })

            logger.info(f"[fetch_models] provider={provider.name} parsed {len(models)} models")
            return {"models": models}

        except httpx.ConnectError:
            return {"models": [], "error": "无法连接到服务器，请检查 API 地址"}
        except httpx.TimeoutException:
            return {"models": [], "error": "连接超时"}
        except Exception as e:
            logger.error(f"[fetch_models] error: {e}")
            return {"models": [], "error": str(e)}

    # ── 聊天管理 ──

    def get_chat_history(self, limit: int = 50) -> list[dict]:
        recent = self._chat_history[-limit:]
        return [m.to_dict() for m in recent]

    def add_message(self, role: str, content: str, provider_id: str = "",
                    model: str = "", tokens_used: int = 0) -> dict:
        msg = ChatMessage(
            id=f"msg_{uuid4().hex[:8]}",
            role=role,
            content=content,
            provider_id=provider_id,
            model=model,
            tokens_used=tokens_used,
        )
        self._chat_history.append(msg)
        self._save_chat_history()
        return msg.to_dict()

    def clear_chat_history(self) -> int:
        count = len(self._chat_history)
        self._chat_history.clear()
        self._save_chat_history()
        return count

    def detect_agent_call(self, content: str) -> Optional[str]:
        content_lower = content.lower()
        if "openclaw" in content_lower or "open claw" in content_lower:
            return "openclaw"
        if "openhanako" in content_lower or "open hanako" in content_lower:
            return "openhanako"
        if "hermes" in content_lower:
            return "hermes"
        for agent, keywords in AGENT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in content_lower:
                    return agent
        return None

    def get_agent_system_prompt(self, agent_name: str) -> str:
        from backend.agent_roles import SUB_AGENTS
        agent_info = SUB_AGENTS.get(agent_name, {})
        return agent_info.get("system_prompt", "")

    async def send_message(self, content: str, system_prompt: str = "", agent_name: str = "") -> dict:
        user_msg = self.add_message("user", content)

        provider = self.get_active_provider()
        if not provider:
            error_msg = "未配置模型供应商。请先在「模型配置」中添加供应商。"
            assistant_msg = self.add_message("assistant", error_msg)
            return {
                "user_message": user_msg,
                "assistant_message": assistant_msg,
                "error": error_msg,
                "agent_called": None,
            }

        try:
            detected_agent = agent_name or self.detect_agent_call(content)

            # ── 智能模型路由（借鉴 hermes-agent）──
            effective_provider = provider
            routing_info = None
            if _HAS_ADVANCED_FEATURES and self._routing_config.get("enabled"):
                routing_decision = should_use_cheap_model(content, self._routing_config)
                if routing_decision.use_cheap_model:
                    cheap_provider = self._providers.get(routing_decision.cheap_provider_id)
                    if cheap_provider and cheap_provider.enabled:
                        effective_provider = cheap_provider
                        # 临时切换到廉价模型
                        original_model = cheap_provider.active_model
                        cheap_provider.active_model = routing_decision.cheap_model
                        routing_info = {
                            "routed_to": "cheap",
                            "reason": routing_decision.reason,
                            "model": routing_decision.cheap_model,
                        }
                        logger.info(f"智能路由：{routing_decision.reason} -> {routing_decision.cheap_model}")
                    else:
                        logger.debug(f"廉价供应商不可用，使用主模型")

            messages = []
            if detected_agent:
                agent_prompt = self.get_agent_system_prompt(detected_agent)
                messages.append({"role": "system", "content": agent_prompt or system_prompt or ""})
            else:
                messages.append({"role": "system", "content": system_prompt or ""})

            recent_history = self._chat_history[-20:]
            for msg in recent_history:
                if msg.role in ("user", "assistant"):
                    messages.append({"role": msg.role, "content": msg.content})

            # ── 上下文压缩检查（借鉴 hermes-agent）──
            if _HAS_ADVANCED_FEATURES and self._context_compressor:
                if self._context_compressor.should_compress(messages):
                    logger.info("上下文接近上限，触发自动压缩...")
                    compression_result = await self._context_compressor.compress(messages)
                    messages = compression_result.messages
                    # 更新聊天历史
                    self._chat_history.clear()
                    for msg in messages:
                        if msg.get("role") in ("user", "assistant"):
                            self.add_message(msg["role"], msg.get("content", ""))

            # ── 带智能重试的模型调用（借鉴 hermes-agent）──
            if _HAS_ADVANCED_FEATURES and self._retry_executor:
                async def call_with_retry():
                    return await self._call_model(effective_provider, messages)

                response_text, tokens_used = await self._retry_executor.execute_with_retry(
                    call_with_retry,
                    context_tokens=estimate_messages_tokens(messages) if _HAS_ADVANCED_FEATURES else 0,
                    context_length=self._context_compressor.context_length if self._context_compressor else 128000,
                )
            else:
                response_text, tokens_used = await self._call_model(effective_provider, messages)

            # 恢复廉价模型的原始设置
            if routing_info and effective_provider != provider:
                effective_provider.active_model = routing_info.get("model", effective_provider.active_model)

            if detected_agent:
                agent_display_name = {
                    "openclaw": "OpenClaw",
                    "openhanako": "OpenHanako",
                    "hermes": "Hermes",
                }.get(detected_agent, detected_agent)
                response_text = f"[{agent_display_name}] {response_text}"

            assistant_msg = self.add_message(
                "assistant", response_text,
                provider_id=effective_provider.id,
                model=effective_provider.active_model,
                tokens_used=tokens_used,
            )

            return {
                "user_message": user_msg,
                "assistant_message": assistant_msg,
                "error": None,
                "agent_called": detected_agent,
                "routing": routing_info,
            }

        except Exception as e:
            # ── 智能错误处理（借鉴 hermes-agent）──
            if _HAS_ADVANCED_FEATURES:
                classified = classify_api_error(
                    e,
                    provider=provider.name if provider else "",
                    model=provider.active_model if provider else "",
                )
                error_msg = f"模型调用失败 [{classified.reason.value}]: {classified.message}"
                logger.error(f"API 错误分类: {classified.reason.value} — {classified.message}")

                # 如果是上下文溢出，尝试压缩后重试
                if classified.should_compress and self._context_compressor:
                    logger.info("检测到上下文溢出，尝试压缩后重试...")
                    try:
                        await self._on_context_overflow()
                        # 重试一次
                        messages = [{"role": "system", "content": system_prompt or ""}]
                        recent_history = self._chat_history[-20:]
                        for msg in recent_history:
                            if msg.role in ("user", "assistant"):
                                messages.append({"role": msg.role, "content": msg.content})
                        response_text, tokens_used = await self._call_model(provider, messages)
                        assistant_msg = self.add_message(
                            "assistant", response_text,
                            provider_id=provider.id,
                            model=provider.active_model,
                            tokens_used=tokens_used,
                        )
                        return {
                            "user_message": user_msg,
                            "assistant_message": assistant_msg,
                            "error": None,
                            "agent_called": detected_agent,
                            "recovered_from": "context_overflow",
                        }
                    except Exception as retry_error:
                        logger.error(f"压缩重试失败: {retry_error}")
            else:
                error_msg = f"模型调用失败: {str(e)}"

            logger.error(error_msg)
            assistant_msg = self.add_message("assistant", error_msg)
            return {
                "user_message": user_msg,
                "assistant_message": assistant_msg,
                "error": error_msg,
            }

    async def _call_model(self, provider: ModelProvider, messages: list[dict]) -> tuple[str, int]:
        logger.info(f"[chat] 调用模型: provider={provider.id} model={provider.active_model} format={provider.api_format}")
        if provider.api_format == "anthropic-messages":
            return await self._call_anthropic(provider, messages)
        elif provider.api_format == "ollama-chat":
            return await self._call_ollama(provider, messages)
        else:
            return await self._call_openai(provider, messages)

    async def _call_openai(self, provider: ModelProvider, messages: list[dict]) -> tuple[str, int]:
        import httpx

        api_base = provider.api_base or "https://api.openai.com/v1"
        url = f"{api_base}/chat/completions"

        headers = {"Content-Type": "application/json"}
        if provider.api_key:
            headers["Authorization"] = f"Bearer {provider.api_key}"

        payload = {
            "model": provider.active_model or "gpt-3.5-turbo",
            "messages": messages,
            "temperature": provider.temperature,
            "max_tokens": provider.max_tokens,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                error_body = resp.text[:500]
                logger.error(f"[call_openai] HTTP {resp.status_code}: {error_body}")
                resp.raise_for_status()
            data = resp.json()

        # 健壮解析（兼容不同 OpenAI 兼容 API 格式）
        content = ""
        if "choices" in data and data["choices"]:
            choice = data["choices"][0]
            msg = choice.get("message", {})
            content = msg.get("content") or msg.get("reasoning_content") or ""
        elif "content" in data:
            # 某些 API 直接返回 content 字段
            c = data["content"]
            if isinstance(c, str):
                content = c
            elif isinstance(c, list) and c:
                block = c[0]
                content = block.get("text", "") if isinstance(block, dict) else str(block)

        if not content:
            logger.error(f"[call_openai] unexpected response: {json.dumps(data, ensure_ascii=False)[:500]}")
            content = str(data)

        tokens = data.get("usage", {}).get("total_tokens", 0)
        return content, tokens

    async def _call_anthropic(self, provider: ModelProvider, messages: list[dict]) -> tuple[str, int]:
        import httpx

        api_base = provider.api_base or "https://api.anthropic.com"
        url = f"{api_base}/v1/messages"

        system_text = ""
        chat_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text = m["content"]
            else:
                chat_messages.append(m)

        headers = {
            "Content-Type": "application/json",
            "x-api-key": provider.api_key,
            "anthropic-version": "2023-06-01",
        }

        payload = {
            "model": provider.active_model or "claude-3-5-sonnet-20241022",
            "messages": chat_messages,
            "max_tokens": provider.max_tokens,
            "temperature": provider.temperature,
        }
        if system_text:
            payload["system"] = system_text

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                error_body = resp.text[:500]
                logger.error(f"[call_anthropic] HTTP {resp.status_code}: {error_body}")
                resp.raise_for_status()
            data = resp.json()

        logger.info(f"[call_anthropic] response keys={list(data.keys())} "
                     f"content_type={type(data.get('content'))} "
                     f"content_len={len(data.get('content', []))}")

        # 健壮解析 content（兼容多种 Anthropic 兼容 API 格式）
        content = ""
        content_blocks = data.get("content", [])

        # 遍历所有 content blocks，优先找 text，其次找 thinking
        text_parts = []
        thinking_parts = []
        for block in content_blocks:
            if isinstance(block, str):
                text_parts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            block_type = block.get("type", "")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "thinking":
                thinking_parts.append(block.get("thinking", ""))
            else:
                # 未知类型，尝试常见字段
                text_parts.append(block.get("text") or block.get("content") or block.get("message") or "")

        # 优先返回 text，没有则返回 thinking
        if text_parts:
            content = "\n".join(text_parts)
        elif thinking_parts:
            content = "\n".join(thinking_parts)

        # 兜底：尝试 choices 格式（某些 Anthropic 兼容 API 用 OpenAI 格式返回）
        if not content and "choices" in data:
            content = data["choices"][0].get("message", {}).get("content", "")

        if not content:
            logger.error(f"[call_anthropic] unexpected response: {json.dumps(data, ensure_ascii=False)[:500]}")
            content = str(data)

        usage = data.get("usage", {})
        tokens = (usage.get("input_tokens", 0)
                  + usage.get("output_tokens", 0)
                  + usage.get("thinking_tokens", 0)
                  + usage.get("cache_read_input_tokens", 0))
        return content, tokens

    async def _call_ollama(self, provider: ModelProvider, messages: list[dict]) -> tuple[str, int]:
        import httpx

        api_base = (provider.api_base or "http://localhost:11434").replace("/v1", "")
        url = f"{api_base}/api/chat"

        payload = {
            "model": provider.active_model or "llama3",
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": provider.temperature,
                "num_predict": provider.max_tokens,
            },
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        content = data["message"]["content"]
        tokens = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)
        return content, tokens


def build_chat_manager_from_env() -> ChatManager:
    storage_dir = os.getenv("CHAT_STORAGE_DIR", "storage")
    return ChatManager(storage_dir=storage_dir)
