"""
shared_context.py - 共享上下文

允许 Agent 在执行过程中共享中间结果和上下文信息。
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class ContextEntry:
    """上下文条目"""
    entry_id: str
    task_id: str
    agent: str
    key: str
    value: Any
    timestamp: float
    ttl: float = 3600  # 生存时间（秒），默认1小时
    tags: Set[str] = field(default_factory=set)

    def is_expired(self) -> bool:
        return time.time() - self.timestamp > self.ttl

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "task_id": self.task_id,
            "agent": self.agent,
            "key": self.key,
            "value": self.value,
            "timestamp": self.timestamp,
            "ttl": self.ttl,
            "tags": list(self.tags),
        }


class SharedContext:
    """
    共享上下文管理器

    功能：
    1. 存储任务执行过程中的中间结果
    2. 允许 Agent 读取其他 Agent 的输出
    3. 支持任务级别的上下文隔离
    4. 自动过期清理
    """

    def __init__(self, persistence_path: Optional[Path] = None):
        self.persistence_path = persistence_path
        self._entries: Dict[str, List[ContextEntry]] = defaultdict(list)
        self._task_contexts: Dict[str, Dict[str, Any]] = {}
        self._lock = None  # 异步锁，在 async 方法中初始化

    async def _ensure_lock(self):
        """确保异步锁已初始化"""
        if self._lock is None:
            import asyncio
            self._lock = asyncio.Lock()

    def set(
        self,
        task_id: str,
        agent: str,
        key: str,
        value: Any,
        ttl: float = 3600,
        tags: Optional[Set[str]] = None,
    ) -> ContextEntry:
        """
        设置上下文值

        Args:
            task_id: 任务 ID
            agent: Agent 名称
            key: 键名
            value: 值
            ttl: 生存时间（秒）
            tags: 标签

        Returns:
            ContextEntry: 创建的上下文条目
        """
        entry = ContextEntry(
            entry_id=str(uuid4()),
            task_id=task_id,
            agent=agent,
            key=key,
            value=value,
            timestamp=time.time(),
            ttl=ttl,
            tags=tags or set(),
        )
        
        self._entries[task_id].append(entry)
        
        # 更新任务上下文快照
        if task_id not in self._task_contexts:
            self._task_contexts[task_id] = {}
        self._task_contexts[task_id][key] = value
        
        logger.debug(f"[shared-context] {agent} set {key} for task {task_id[:8]}...")
        
        return entry

    def get(
        self,
        task_id: str,
        key: str,
        default: Any = None,
    ) -> Optional[Any]:
        """
        获取上下文值

        Args:
            task_id: 任务 ID
            key: 键名
            default: 默认值

        Returns:
            值或默认值
        """
        entries = self._entries.get(task_id, [])
        
        # 找到最新的非过期条目
        for entry in reversed(entries):
            if entry.key == key and not entry.is_expired():
                return entry.value
        
        # 尝试从快照获取
        return self._task_contexts.get(task_id, {}).get(key, default)

    def get_by_agent(
        self,
        task_id: str,
        agent: str,
    ) -> Dict[str, Any]:
        """
        获取某个 Agent 在任务中设置的所有值

        Args:
            task_id: 任务 ID
            agent: Agent 名称

        Returns:
            Dict[str, Any]: 键值对字典
        """
        entries = self._entries.get(task_id, [])
        result = {}
        
        for entry in entries:
            if entry.agent == agent and not entry.is_expired():
                result[entry.key] = entry.value
        
        return result

    def get_all(self, task_id: str) -> Dict[str, Any]:
        """
        获取任务的所有上下文值

        Args:
            task_id: 任务 ID

        Returns:
            Dict[str, Any]: 合并后的上下文
        """
        entries = self._entries.get(task_id, [])
        result = {}
        
        for entry in entries:
            if not entry.is_expired():
                result[entry.key] = entry.value
        
        return result

    def query(
        self,
        task_id: str,
        tags: Optional[Set[str]] = None,
    ) -> List[ContextEntry]:
        """
        查询上下文条目

        Args:
            task_id: 任务 ID
            tags: 标签过滤

        Returns:
            List[ContextEntry]: 匹配的条目
        """
        entries = self._entries.get(task_id, [])
        result = []
        
        for entry in entries:
            if entry.is_expired():
                continue
            if tags and not entry.tags.intersection(tags):
                continue
            result.append(entry)
        
        return result

    def delete(self, task_id: str, key: str) -> bool:
        """
        删除上下文值

        Args:
            task_id: 任务 ID
            key: 键名

        Returns:
            bool: 是否删除成功
        """
        entries = self._entries.get(task_id, [])
        
        for entry in entries:
            if entry.key == key:
                entry.ttl = 0  # 立即过期
        
        # 从快照中删除
        if task_id in self._task_contexts:
            self._task_contexts[task_id].pop(key, None)
        
        return True

    def clear_task(self, task_id: str) -> int:
        """
        清除任务的所有上下文

        Args:
            task_id: 任务 ID

        Returns:
            int: 清除的条目数
        """
        count = len(self._entries.get(task_id, []))
        
        self._entries[task_id] = []
        self._task_contexts.pop(task_id, None)
        
        logger.info(f"[shared-context] Cleared {count} entries for task {task_id[:8]}...")
        
        return count

    def cleanup_expired(self) -> int:
        """
        清理过期的上下文条目

        Returns:
            int: 清理的条目数
        """
        count = 0
        
        for task_id, entries in list(self._entries.items()):
            original_count = len(entries)
            self._entries[task_id] = [e for e in entries if not e.is_expired()]
            count += original_count - len(self._entries[task_id])
            
            # 清理空的任务
            if not self._entries[task_id]:
                self._entries.pop(task_id, None)
        
        if count > 0:
            logger.debug(f"[shared-context] Cleaned up {count} expired entries")
        
        return count

    def get_task_summary(self, task_id: str) -> Dict[str, Any]:
        """
        获取任务的上下文摘要

        Args:
            task_id: 任务 ID

        Returns:
            Dict[str, Any]: 摘要信息
        """
        entries = self._entries.get(task_id, [])
        active_entries = [e for e in entries if not e.is_expired()]
        
        agents = set(e.agent for e in active_entries)
        keys = set(e.key for e in active_entries)
        tags = set()
        for e in active_entries:
            tags.update(e.tags)
        
        return {
            "task_id": task_id,
            "total_entries": len(entries),
            "active_entries": len(active_entries),
            "agents": list(agents),
            "keys": list(keys),
            "tags": list(tags),
        }

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total_entries = sum(len(e) for e in self._entries.values())
        active_entries = sum(
            len([e for e in entries if not e.is_expired()])
            for entries in self._entries.values()
        )
        
        return {
            "total_tasks": len(self._entries),
            "total_entries": total_entries,
            "active_entries": active_entries,
            "expired_entries": total_entries - active_entries,
        }

    def export_task_context(self, task_id: str) -> str:
        """
        导出任务上下文为 JSON 字符串

        Args:
            task_id: 任务 ID

        Returns:
            str: JSON 格式的上下文
        """
        context = self.get_all(task_id)
        return json.dumps(context, ensure_ascii=False, indent=2)

    def import_task_context(self, task_id: str, data: Dict[str, Any]) -> None:
        """
        导入任务上下文

        Args:
            task_id: 任务 ID
            data: 上下文数据
        """
        for key, value in data.items():
            self.set(
                task_id=task_id,
                agent="imported",
                key=key,
                value=value,
                ttl=7200,  # 导入的数据保留2小时
            )
        
        logger.info(f"[shared-context] Imported {len(data)} entries for task {task_id[:8]}...")
