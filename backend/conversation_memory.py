"""
conversation_memory.py — 跨会话记忆管理

使用 ChromaDB（已安装）做向量记忆，支持：
  - add(session_id, user, assistant, metadata)：存储对话
  - retrieve_context(session_id, query, k=3)：语义检索相关记忆
  - clear_session(session_id)：清除某会话记忆
  - get_recent(session_id, k=5)：获取最近 k 条记忆
"""

import logging
import time
import uuid
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import chromadb
    from chromadb.utils import embedding_functions
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False

# ── 嵌入函数 ────────────────────────────────────────────────

def _get_embedding_function():
    """获取嵌入函数（优先 OpenAI，可降级为本地 MiniMax）"""
    import os

    # 尝试 OpenAI（需要 API Key）
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        return embedding_functions.OpenAIEmbeddingFunction(
            api_key=openai_key,
            model_name="text-embedding-3-small",
        )

    # 降级：使用 Chroma 内置默认嵌入（轻量，支持中英文）
    return embedding_functions.DefaultEmbeddingFunction()


# ── 记忆类 ──────────────────────────────────────────────────

class ConversationMemory:
    """
    向量记忆：存储 + 语义检索
    使用 ChromaDB，collection 名固定为 "agent_conversations"
    """

    COLLECTION_NAME = "agent_conversations"

    def __init__(self, persist_dir: str = ""):
        if not HAS_CHROMADB:
            raise ImportError("ChromaDB not installed. Run: pip install chromadb")

        # 持久化存储（可选，不传则用临时内存数据库）
        if persist_dir:
            self.client = chromadb.PersistentClient(path=persist_dir)
        else:
            self.client = chromadb.Client()

        try:
            self.ef = _get_embedding_function()
            self.collection = self.client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                embedding_function=self.ef,
                metadata={"description": "Agent conversation memory"},
            )
        except Exception as e:
            # 某些部署环境不支持嵌入，降级到无嵌入模式
            logger.warning(f"[Memory] ChromaDB embedding failed: {e}, using raw collection")
            self.collection = self.client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"description": "Agent conversation memory"},
            )

        logger.info(f"[Memory] Initialized, collection count: {self.collection.count()}")

    def add(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        metadata: Optional[dict] = None,
    ) -> str:
        """
        添加一组对话记忆。
        Returns: memory record id
        """
        record_id = f"{session_id}_{int(time.time() * 1000)}"
        combined_text = (
            f"User: {user_message}\n"
            f"Assistant: {assistant_message}"
        )

        meta = {
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "user_preview": user_message[:100],
            **(metadata or {}),
        }

        try:
            self.collection.add(
                documents=[combined_text],
                metadatas=[meta],
                ids=[record_id],
            )
            logger.debug(f"[Memory] Added record {record_id} for session {session_id}")
        except Exception as e:
            logger.warning(f"[Memory] add failed: {e}")

        return record_id

    def retrieve_context(
        self,
        session_id: str,
        query: str,
        k: int = 3,
    ) -> list[str]:
        """
        语义检索：返回与 query 相关的历史对话文本列表。
        仅返回同一 session_id 的记忆。
        """
        if self.collection.count() == 0:
            return []

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=k,
                where={"session_id": session_id},
            )
            docs = results.get("documents", [])
            return docs[0] if docs else []
        except Exception as e:
            logger.warning(f"[Memory] retrieve_context failed: {e}")
            return []

    def get_recent(self, session_id: str, k: int = 5) -> list[dict]:
        """获取最近 k 条记忆（按时间倒序）"""
        try:
            results = self.collection.get(
                where={"session_id": session_id},
                limit=k,
            )
            records = []
            for doc, meta in zip(
                results.get("documents", []),
                results.get("metadatas", []),
            ):
                if doc and meta:
                    # 尝试拆分 user / assistant
                    parts = doc.split("Assistant:", 1)
                    user_part = parts[0].replace("User:", "").strip() if parts else doc
                    assistant_part = parts[1].strip() if len(parts) > 1 else ""
                    records.append({
                        "user": user_part,
                        "assistant": assistant_part,
                        "timestamp": meta.get("timestamp", ""),
                    })
            return records
        except Exception as e:
            logger.warning(f"[Memory] get_recent failed: {e}")
            return []

    def clear_session(self, session_id: str) -> int:
        """清除某会话的所有记忆，返回删除数量"""
        try:
            results = self.collection.get(where={"session_id": session_id})
            ids = results.get("ids", [])
            if ids:
                self.collection.delete(ids=ids)
                logger.info(f"[Memory] Cleared {len(ids)} records for session {session_id}")
                return len(ids)
        except Exception as e:
            logger.warning(f"[Memory] clear_session failed: {e}")
        return 0

    def count(self) -> int:
        """返回总记忆条数"""
        try:
            return self.collection.count()
        except Exception:
            return 0