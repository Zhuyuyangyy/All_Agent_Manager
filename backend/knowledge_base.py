"""
knowledge_base.py — 知识库模块

为 Agent 系统提供结构化知识存储与检索能力。
每个知识条目包含标题、正文、标签、分类，支持关键词匹配和相关度排序。

设计理念：
  - 轻量，无外部向量数据库依赖
  - 与 skill_memory.py 风格一致，JSON 文件持久化
  - 支持从任务结果中自动提炼知识
  - 知识条目可被 Agent 在执行任务时引用，提供上下文
"""

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class KnowledgeType(StrEnum):
    """知识类型"""
    FACT = "fact"              # 事实性知识（定义、参数、配置值）
    PROCEDURE = "procedure"    # 流程性知识（步骤、操作指南）
    REFERENCE = "reference"    # 参考资料（链接、文档位置、API 地址）
    CONTEXT = "context"        # 上下文信息（项目背景、用户偏好、约束条件）
    LESSON = "lesson"          # 经验教训（踩过的坑、最佳实践）


class KnowledgeStatus(StrEnum):
    """知识状态"""
    ACTIVE = "active"
    OUTDATED = "outdated"      # 标记为过时，搜索时不返回但保留记录
    ARCHIVED = "archived"


@dataclass
class KnowledgeEntry:
    """知识条目"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    content: str = ""
    type: KnowledgeType = KnowledgeType.FACT
    status: KnowledgeStatus = KnowledgeStatus.ACTIVE

    # 分类与标签
    category: str = ""             # 所属分类（如 "openclaw", "wechat", "deploy"）
    tags: list[str] = field(default_factory=list)
    source: str = ""               # 来源（任务 ID、手动添加、自动提炼）

    # 关联
    related_task_id: str | None = None   # 关联的任务 ID
    related_agent: str | None = None     # 关联的 Agent
    related_skill_id: str | None = None  # 关联的技能 ID

    # 匹配权重
    keywords: list[str] = field(default_factory=list)   # 显式关键词
    importance: int = 5              # 重要性 1-10，影响排序

    # 使用统计
    hit_count: int = 0               # 被检索命中次数
    last_hit_at: str | None = None

    # 元数据
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    created_by: str = "manual"       # manual | auto | import
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "type": self.type.value,
            "status": self.status.value,
            "category": self.category,
            "tags": self.tags,
            "source": self.source,
            "related_task_id": self.related_task_id,
            "related_agent": self.related_agent,
            "related_skill_id": self.related_skill_id,
            "keywords": self.keywords,
            "importance": self.importance,
            "hit_count": self.hit_count,
            "last_hit_at": self.last_hit_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "created_by": self.created_by,
            "metadata": self.metadata,
        }

    def record_hit(self) -> None:
        """记录一次被命中"""
        self.hit_count += 1
        self.last_hit_at = datetime.now().isoformat()


class KnowledgeBase:
    """
    知识库。
    存储、检索、匹配知识条目。
    """

    def __init__(self, storage_path: str | Path = "storage/knowledge.json"):
        self.storage_path = Path(storage_path)
        self._entries: dict[str, KnowledgeEntry] = {}
        self._load()

    # ── 持久化 ──

    def _load(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            for item in data.get("entries", []):
                entry = self._deserialize(item)
                self._entries[entry.id] = entry
        except Exception:
            pass

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "updated_at": datetime.now().isoformat(),
            "entries": [e.to_dict() for e in self._entries.values()],
        }
        self.storage_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _deserialize(data: dict) -> KnowledgeEntry:
        return KnowledgeEntry(
            id=data["id"],
            title=data.get("title", ""),
            content=data.get("content", ""),
            type=KnowledgeType(data.get("type", "fact")),
            status=KnowledgeStatus(data.get("status", "active")),
            category=data.get("category", ""),
            tags=data.get("tags", []),
            source=data.get("source", ""),
            related_task_id=data.get("related_task_id"),
            related_agent=data.get("related_agent"),
            related_skill_id=data.get("related_skill_id"),
            keywords=data.get("keywords", []),
            importance=data.get("importance", 5),
            hit_count=data.get("hit_count", 0),
            last_hit_at=data.get("last_hit_at"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            created_by=data.get("created_by", "manual"),
            metadata=data.get("metadata", {}),
        )

    # ── CRUD ──

    def add_entry(self, entry: KnowledgeEntry) -> KnowledgeEntry:
        """添加知识条目"""
        self._entries[entry.id] = entry
        self._save()
        return entry

    def get_entry(self, entry_id: str) -> KnowledgeEntry | None:
        return self._entries.get(entry_id)

    def update_entry(self, entry: KnowledgeEntry) -> KnowledgeEntry:
        entry.updated_at = datetime.now().isoformat()
        self._entries[entry.id] = entry
        self._save()
        return entry

    def delete_entry(self, entry_id: str) -> bool:
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._save()
            return True
        return False

    def list_entries(
        self,
        status: KnowledgeStatus | None = None,
        category: str | None = None,
        knowledge_type: KnowledgeType | None = None,
        tag: str | None = None,
        agent: str | None = None,
    ) -> list[KnowledgeEntry]:
        """列出知识条目，支持过滤"""
        entries = list(self._entries.values())

        if status:
            entries = [e for e in entries if e.status == status]
        if category:
            entries = [e for e in entries if e.category == category]
        if knowledge_type:
            entries = [e for e in entries if e.type == knowledge_type]
        if tag:
            entries = [e for e in entries if tag in e.tags]
        if agent:
            entries = [e for e in entries if e.related_agent == agent]

        # 默认按重要性降序
        entries.sort(key=lambda e: e.importance, reverse=True)
        return entries

    # ── 搜索与匹配 ──

    def search(
        self,
        query: str,
        category: str | None = None,
        knowledge_type: KnowledgeType | None = None,
        agent: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """
        搜索知识库。
        返回匹配结果列表，每项包含 entry 和 score。
        """
        query_lower = query.lower()
        query_tokens = self._tokenize(query_lower)
        results: list[tuple[KnowledgeEntry, float]] = []

        for entry in self._entries.values():
            if entry.status != KnowledgeStatus.ACTIVE:
                continue
            if category and entry.category != category:
                continue
            if knowledge_type and entry.type != knowledge_type:
                continue
            if agent and entry.related_agent != agent:
                continue

            score = self._score_entry(entry, query_lower, query_tokens)
            if score > 0:
                results.append((entry, score))

        # 按分数降序
        results.sort(key=lambda x: x[1], reverse=True)

        # 记录命中
        for entry, _ in results[:limit]:
            entry.record_hit()
        if results:
            self._save()

        return [
            {
                "entry": entry.to_dict(),
                "score": round(score, 2),
            }
            for entry, score in results[:limit]
        ]

    def get_context_for_task(
        self,
        task_goal: str,
        agent: str | None = None,
        limit: int = 3,
    ) -> str:
        """
        为任务获取相关知识上下文。
        返回拼接好的文本，可直接注入 Agent 的 system prompt。
        """
        results = self.search(task_goal, agent=agent, limit=limit)
        if not results:
            return ""

        parts = ["## 相关知识"]
        for item in results:
            entry = item["entry"]
            parts.append(f"\n### {entry['title']} [{entry['type']}]")
            parts.append(entry["content"])
            if entry["tags"]:
                parts.append(f"标签: {', '.join(entry['tags'])}")

        return "\n".join(parts)

    def _score_entry(
        self,
        entry: KnowledgeEntry,
        query_lower: str,
        query_tokens: list[str],
    ) -> float:
        """计算条目与查询的相关度分数"""
        score = 0.0

        # 标题精确包含
        title_lower = entry.title.lower()
        if query_lower in title_lower:
            score += 20
        else:
            # 标题 token 匹配
            title_tokens = self._tokenize(title_lower)
            overlap = set(query_tokens) & set(title_tokens)
            score += len(overlap) * 5

        # 显式关键词匹配
        for kw in entry.keywords:
            if kw.lower() in query_lower or query_lower in kw.lower():
                score += 15
            elif any(t in kw.lower() for t in query_tokens):
                score += 8

        # 标签匹配
        for tag in entry.tags:
            if tag.lower() in query_lower:
                score += 10
            elif any(t in tag.lower() for t in query_tokens):
                score += 4

        # 内容 token 匹配
        content_tokens = self._tokenize(entry.content.lower())
        content_overlap = set(query_tokens) & set(content_tokens)
        score += len(content_overlap) * 2

        # 分类匹配
        if entry.category and entry.category.lower() in query_lower:
            score += 5

        # 重要性加成 (1-10 → 0-5)
        score += entry.importance * 0.5

        # 使用频率加成（对数衰减）
        if entry.hit_count > 0:
            score += min(3.0, entry.hit_count * 0.3)

        return score

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """简单分词：按非字母数字字符拆分，过滤短 token"""
        tokens = re.split(r'[^\w一-鿿]+', text)
        return [t for t in tokens if len(t) >= 2]

    # ── 自动提炼 ──

    def extract_from_task(
        self,
        task_id: str,
        task_goal: str,
        result_payload: str,
        agent: str,
    ) -> KnowledgeEntry | None:
        """
        从任务结果中自动提炼知识条目。
        调用方可自行判断是否值得提炼，这里只负责构造条目。
        """
        if not result_payload or len(result_payload.strip()) < 20:
            return None

        # 提取标题：取任务目标的前 50 字符
        title = task_goal[:50].strip()
        if len(task_goal) > 50:
            title += "..."

        entry = KnowledgeEntry(
            title=title,
            content=result_payload[:2000],  # 限制长度
            type=KnowledgeType.LESSON,
            category=agent,
            tags=[agent, "auto-extracted"],
            source=f"task:{task_id}",
            related_task_id=task_id,
            related_agent=agent,
            importance=4,  # 自动提炼的默认重要性较低
            created_by="auto",
        )

        self._entries[entry.id] = entry
        self._save()
        return entry

    # ── 批量导入 ──

    def import_entries(self, entries: list[dict]) -> int:
        """批量导入知识条目，返回成功导入的数量"""
        count = 0
        for data in entries:
            try:
                entry = KnowledgeEntry(
                    title=data.get("title", ""),
                    content=data.get("content", ""),
                    type=KnowledgeType(data.get("type", "fact")),
                    category=data.get("category", ""),
                    tags=data.get("tags", []),
                    keywords=data.get("keywords", []),
                    importance=data.get("importance", 5),
                    created_by="import",
                )
                self._entries[entry.id] = entry
                count += 1
            except Exception:
                continue
        if count > 0:
            self._save()
        return count

    # ── 统计 ──

    def get_stats(self) -> dict:
        all_entries = list(self._entries.values())
        active = [e for e in all_entries if e.status == KnowledgeStatus.ACTIVE]

        by_type: dict[str, int] = {}
        by_category: dict[str, int] = {}
        for e in active:
            by_type[e.type.value] = by_type.get(e.type.value, 0) + 1
            if e.category:
                by_category[e.category] = by_category.get(e.category, 0) + 1

        return {
            "total": len(all_entries),
            "active": len(active),
            "outdated": sum(1 for e in all_entries if e.status == KnowledgeStatus.OUTDATED),
            "by_type": by_type,
            "by_category": by_category,
            "total_hits": sum(e.hit_count for e in all_entries),
            "top_entries": sorted(
                [e.to_dict() for e in active],
                key=lambda x: x["hit_count"],
                reverse=True,
            )[:5],
        }

    # ── 状态管理 ──

    def mark_outdated(self, entry_id: str) -> bool:
        entry = self._entries.get(entry_id)
        if entry:
            entry.status = KnowledgeStatus.OUTDATED
            entry.updated_at = datetime.now().isoformat()
            self._save()
            return True
        return False

    def archive_entry(self, entry_id: str) -> bool:
        entry = self._entries.get(entry_id)
        if entry:
            entry.status = KnowledgeStatus.ARCHIVED
            entry.updated_at = datetime.now().isoformat()
            self._save()
            return True
        return False

    def reactivate_entry(self, entry_id: str) -> bool:
        entry = self._entries.get(entry_id)
        if entry:
            entry.status = KnowledgeStatus.ACTIVE
            entry.updated_at = datetime.now().isoformat()
            self._save()
            return True
        return False


def build_knowledge_base_from_env() -> KnowledgeBase:
    """从环境变量构建知识库"""
    storage_path = os.getenv("KNOWLEDGE_STORAGE_PATH", "storage/knowledge.json")
    return KnowledgeBase(storage_path=storage_path)
