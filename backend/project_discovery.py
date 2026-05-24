"""
project_discovery.py — 主动任务发现模块

系统主动扫描项目、文件、API 等来源，发现待处理任务。
每个 TaskSource 实现 discover() 方法，返回标准化的 DiscoveredTask 列表。
"""

import json
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from backend.models import AgentChoice


class TaskPriority(StrEnum):
    """任务优先级"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskType(StrEnum):
    """任务类型"""
    BUG_FIX = "bug_fix"          # 修 bug
    FEATURE = "feature"          # 新功能
    RESEARCH = "research"        # 调研分析
    CODE_REVIEW = "code_review"  # 代码审查
    DOCUMENTATION = "documentation"  # 文档
    MAINTENANCE = "maintenance"  # 维护
    CUSTOM = "custom"            # 自定义


@dataclass
class DiscoveredTask:
    """发现的任务（标准化格式）"""
    id: str
    goal: str                          # 任务目标描述
    source: str                        # 来源标识（如 "file_scanner", "git_watcher"）
    task_type: TaskType = TaskType.CUSTOM
    priority: TaskPriority = TaskPriority.NORMAL
    suggested_agent: AgentChoice = AgentChoice.AUTO
    context: dict[str, Any] = field(default_factory=dict)  # 额外上下文
    discovered_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "goal": self.goal,
            "source": self.source,
            "task_type": self.task_type.value,
            "priority": self.priority.value,
            "suggested_agent": self.suggested_agent.value,
            "context": self.context,
            "discovered_at": self.discovered_at,
            "metadata": self.metadata,
        }


class TaskSource(ABC):
    """任务来源基类"""

    @property
    @abstractmethod
    def source_id(self) -> str:
        """来源标识"""
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """来源名称"""
        ...

    @abstractmethod
    def discover(self) -> list[DiscoveredTask]:
        """发现任务"""
        ...

    def is_enabled(self) -> bool:
        """是否启用"""
        return True


# ── 来源 1：文件扫描 ──

class FileScannerSource(TaskSource):
    """
    扫描指定目录，寻找 TODO/FIXME/HACK 注释、README 任务等。
    """

    TODO_PATTERNS = [
        re.compile(r"#\s*TODO[:\s]*(?P<text>.+)", re.IGNORECASE),
        re.compile(r"//\s*TODO[:\s]*(?P<text>.+)", re.IGNORECASE),
        re.compile(r"<!--\s*TODO[:\s]*(?P<text>.+?)\s*-->", re.IGNORECASE),
        re.compile(r"FIXME[:\s]*(?P<text>.+)", re.IGNORECASE),
        re.compile(r"HACK[:\s]*(?P<text>.+)", re.IGNORECASE),
    ]

    SCAN_EXTENSIONS = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".vue", ".html", ".css",
        ".md", ".txt", ".yaml", ".yml", ".toml", ".json",
    }

    def __init__(
        self,
        scan_dirs: list[str] | None = None,
        max_depth: int = 5,
        exclude_patterns: list[str] | None = None,
    ):
        self.scan_dirs = scan_dirs or []
        self.max_depth = max_depth
        self.exclude_patterns = exclude_patterns or [
            "node_modules", ".git", "__pycache__", ".venv", "venv",
            "dist", "build", ".next", ".nuxt", "storage",
        ]

    @property
    def source_id(self) -> str:
        return "file_scanner"

    @property
    def source_name(self) -> str:
        return "文件扫描"

    def is_enabled(self) -> bool:
        return len(self.scan_dirs) > 0

    def discover(self) -> list[DiscoveredTask]:
        tasks = []
        for scan_dir in self.scan_dirs:
            dir_path = Path(scan_dir)
            if not dir_path.exists():
                continue
            tasks.extend(self._scan_directory(dir_path, 0))
        return tasks

    def _scan_directory(self, directory: Path, depth: int) -> list[DiscoveredTask]:
        if depth > self.max_depth:
            return []

        tasks = []
        try:
            for item in directory.iterdir():
                # 跳过排除的目录
                if item.is_dir() and item.name in self.exclude_patterns:
                    continue
                if item.is_dir():
                    tasks.extend(self._scan_directory(item, depth + 1))
                elif item.is_file() and item.suffix in self.SCAN_EXTENSIONS:
                    tasks.extend(self._scan_file(item))
        except PermissionError:
            pass
        return tasks

    def _scan_file(self, file_path: Path) -> list[DiscoveredTask]:
        tasks = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")

            for line_num, line in enumerate(lines, 1):
                for pattern in self.TODO_PATTERNS:
                    match = pattern.search(line)
                    if match:
                        text = match.group("text").strip()
                        if text and len(text) > 3:  # 过滤太短的
                            task_type = self._classify_todo(text)
                            priority = self._estimate_priority(text)
                            tasks.append(DiscoveredTask(
                                id=f"todo_{file_path.name}_{line_num}",
                                goal=f"[{file_path.name}:{line_num}] {text}",
                                source=self.source_id,
                                task_type=task_type,
                                priority=priority,
                                context={
                                    "file": str(file_path),
                                    "line": line_num,
                                    "original_line": line.strip(),
                                },
                            ))
        except Exception:
            pass
        return tasks

    def _classify_todo(self, text: str) -> TaskType:
        text_lower = text.lower()
        if any(w in text_lower for w in ("bug", "fix", "error", "broken")):
            return TaskType.BUG_FIX
        if any(w in text_lower for w in ("feature", "add", "implement", "new")):
            return TaskType.FEATURE
        if any(w in text_lower for w in ("research", "investigate", "analyze")):
            return TaskType.RESEARCH
        if any(w in text_lower for w in ("doc", "readme", "comment")):
            return TaskType.DOCUMENTATION
        return TaskType.CUSTOM

    def _estimate_priority(self, text: str) -> TaskPriority:
        text_lower = text.lower()
        if any(w in text_lower for w in ("urgent", "critical", "hotfix", "紧急")):
            return TaskPriority.URGENT
        if any(w in text_lower for w in ("important", "priority", "重要")):
            return TaskPriority.HIGH
        return TaskPriority.NORMAL


# ── 来源 2：Git 仓库监控 ──

class GitProjectSource(TaskSource):
    """
    扫描 Git 仓库，发现未完成的工作：
    - 未提交的变更
    - 未合并的分支
    - Issue / TODO 在 commit message 中
    """

    def __init__(self, repo_dirs: list[str] | None = None):
        self.repo_dirs = repo_dirs or []

    @property
    def source_id(self) -> str:
        return "git_project"

    @property
    def source_name(self) -> str:
        return "Git 仓库"

    def is_enabled(self) -> bool:
        return len(self.repo_dirs) > 0

    def discover(self) -> list[DiscoveredTask]:
        tasks = []
        for repo_dir in self.repo_dirs:
            repo_path = Path(repo_dir)
            if not (repo_path / ".git").exists():
                continue
            tasks.extend(self._scan_repo(repo_path))
        return tasks

    def _scan_repo(self, repo_path: Path) -> list[DiscoveredTask]:
        tasks = []

        # 检查未提交的变更
        try:
            import subprocess
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.stdout.strip():
                changed_files = [line[3:] for line in result.stdout.strip().split("\n") if line.strip()]
                tasks.append(DiscoveredTask(
                    id=f"git_uncommitted_{repo_path.name}",
                    goal=f"仓库 {repo_path.name} 有 {len(changed_files)} 个未提交的文件变更，需要处理",
                    source=self.source_id,
                    task_type=TaskType.MAINTENANCE,
                    priority=TaskPriority.LOW,
                    context={
                        "repo": str(repo_path),
                        "changed_files": changed_files[:10],  # 最多显示10个
                    },
                ))
        except Exception:
            pass

        # 检查未合并的分支
        try:
            import subprocess
            result = subprocess.run(
                ["git", "branch", "--no-merged", "main"],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.stdout.strip():
                branches = [b.strip().lstrip("* ") for b in result.stdout.strip().split("\n") if b.strip()]
                if branches:
                    tasks.append(DiscoveredTask(
                        id=f"git_unmerged_{repo_path.name}",
                        goal=f"仓库 {repo_path.name} 有 {len(branches)} 个未合并分支，需要审查合并",
                        source=self.source_id,
                        task_type=TaskType.CODE_REVIEW,
                        priority=TaskPriority.LOW,
                        context={
                            "repo": str(repo_path),
                            "branches": branches[:5],
                        },
                    ))
        except Exception:
            pass

        return tasks


# ── 来源 3：可配置任务源（JSON/YAML 文件）──

class ConfigurableSource(TaskSource):
    """
    从配置文件读取任务列表。
    配置文件格式：
    [
      {
        "goal": "任务描述",
        "type": "feature",
        "priority": "high",
        "agent": "openclaw"
      }
    ]
    """

    def __init__(self, config_path: str | None = None):
        self.config_path = config_path

    @property
    def source_id(self) -> str:
        return "configurable"

    @property
    def source_name(self) -> str:
        return "配置任务"

    def is_enabled(self) -> bool:
        return self.config_path is not None and Path(self.config_path).exists()

    def discover(self) -> list[DiscoveredTask]:
        if not self.config_path:
            return []

        config_file = Path(self.config_path)
        if not config_file.exists():
            return []

        try:
            content = config_file.read_text(encoding="utf-8")
            items = json.loads(content)
            if not isinstance(items, list):
                return []

            tasks = []
            for i, item in enumerate(items):
                if not isinstance(item, dict) or "goal" not in item:
                    continue
                tasks.append(DiscoveredTask(
                    id=f"config_{i}",
                    goal=item["goal"],
                    source=self.source_id,
                    task_type=TaskType(item.get("type", "custom")),
                    priority=TaskPriority(item.get("priority", "normal")),
                    suggested_agent=AgentChoice(item.get("agent", "auto")),
                    context=item,
                ))
            return tasks
        except Exception:
            return []


# ── 来源 4：API 轮询 ──

class APIPollingSource(TaskSource):
    """
    轮询外部 API 获取任务。
    API 返回格式：[{ "goal": "...", "type": "...", "priority": "..." }]
    """

    def __init__(self, api_url: str | None = None, poll_interval: int = 60):
        self.api_url = api_url
        self.poll_interval = poll_interval
        self._last_poll = 0

    @property
    def source_id(self) -> str:
        return "api_polling"

    @property
    def source_name(self) -> str:
        return "API 轮询"

    def is_enabled(self) -> bool:
        return self.api_url is not None

    def discover(self) -> list[DiscoveredTask]:
        if not self.api_url:
            return []

        now = time.time()
        if now - self._last_poll < self.poll_interval:
            return []

        self._last_poll = now

        try:
            import httpx
            response = httpx.get(self.api_url, timeout=10)
            response.raise_for_status()
            items = response.json()

            if not isinstance(items, list):
                return []

            tasks = []
            for i, item in enumerate(items):
                if not isinstance(item, dict) or "goal" not in item:
                    continue
                tasks.append(DiscoveredTask(
                    id=f"api_{i}_{int(now)}",
                    goal=item["goal"],
                    source=self.source_id,
                    task_type=TaskType(item.get("type", "custom")),
                    priority=TaskPriority(item.get("priority", "normal")),
                    suggested_agent=AgentChoice(item.get("agent", "auto")),
                ))
            return tasks
        except Exception:
            return []


# ── 来源 5：关键词触发（微信消息增强）──

class KeywordTriggerSource(TaskSource):
    """
    监听特定关键词，触发预定义任务。
    配置格式：
    {
      "关键词": {
        "goal": "触发的任务描述",
        "agent": "hermes"
      }
    }
    """

    def __init__(self, triggers: dict | None = None):
        self.triggers = triggers or {}
        self._pending_messages: list[dict] = []

    @property
    def source_id(self) -> str:
        return "keyword_trigger"

    @property
    def source_name(self) -> str:
        return "关键词触发"

    def add_message(self, text: str, sender: str = "", chat_id: str = "") -> None:
        """添加待检查的消息"""
        self._pending_messages.append({
            "text": text,
            "sender": sender,
            "chat_id": chat_id,
            "timestamp": datetime.now().isoformat(),
        })

    def is_enabled(self) -> bool:
        return len(self.triggers) > 0

    def discover(self) -> list[DiscoveredTask]:
        if not self._pending_messages:
            return []

        tasks = []
        remaining = []

        for msg in self._pending_messages:
            matched = False
            for keyword, config in self.triggers.items():
                if keyword.lower() in msg["text"].lower():
                    tasks.append(DiscoveredTask(
                        id=f"trigger_{keyword}_{int(time.time())}",
                        goal=config.get("goal", msg["text"]),
                        source=self.source_id,
                        task_type=TaskType(config.get("type", "custom")),
                        priority=TaskPriority(config.get("priority", "normal")),
                        suggested_agent=AgentChoice(config.get("agent", "auto")),
                        context={
                            "trigger_keyword": keyword,
                            "original_message": msg["text"],
                            "sender": msg["sender"],
                            "chat_id": msg["chat_id"],
                        },
                    ))
                    matched = True
                    break  # 一条消息只匹配一个触发器

            if not matched:
                remaining.append(msg)

        self._pending_messages = remaining
        return tasks


# ── 任务发现管理器 ──

class DiscoveryManager:
    """
    管理所有任务来源，统一调度发现流程。
    """

    def __init__(self):
        self._sources: list[TaskSource] = []
        self._discovered_tasks: dict[str, DiscoveredTask] = {}
        self._scan_history: list[dict] = []

    def register_source(self, source: TaskSource) -> None:
        """注册任务来源"""
        self._sources.append(source)

    def get_sources(self) -> list[dict]:
        """获取所有来源信息"""
        return [
            {
                "id": s.source_id,
                "name": s.source_name,
                "enabled": s.is_enabled(),
            }
            for s in self._sources
        ]

    def scan_all(self) -> list[DiscoveredTask]:
        """扫描所有来源，返回新发现的任务（去重）"""
        all_tasks = []
        scan_time = datetime.now().isoformat()
        scan_result = {"time": scan_time, "sources": {}, "new_tasks": 0}

        for source in self._sources:
            if not source.is_enabled():
                continue

            try:
                tasks = source.discover()
                new_tasks = [
                    t for t in tasks
                    if t.id not in self._discovered_tasks
                ]
                all_tasks.extend(new_tasks)
                scan_result["sources"][source.source_id] = {
                    "found": len(tasks),
                    "new": len(new_tasks),
                }
            except Exception as e:
                scan_result["sources"][source.source_id] = {
                    "error": str(e),
                }

        # 添加到已发现列表
        for task in all_tasks:
            self._discovered_tasks[task.id] = task

        scan_result["new_tasks"] = len(all_tasks)
        self._scan_history.append(scan_result)

        # 保留最近 100 条扫描历史
        if len(self._scan_history) > 100:
            self._scan_history = self._scan_history[-100:]

        return all_tasks

    def get_pending_tasks(self) -> list[DiscoveredTask]:
        """获取所有待处理的任务"""
        return list(self._discovered_tasks.values())

    def mark_task_taken(self, task_id: str) -> bool:
        """标记任务已被取走（从待处理列表移除）"""
        if task_id in self._discovered_tasks:
            del self._discovered_tasks[task_id]
            return True
        return False

    def get_scan_history(self, limit: int = 20) -> list[dict]:
        """获取扫描历史"""
        return self._scan_history[-limit:]

    def clear_all(self) -> int:
        """清空所有待处理任务"""
        count = len(self._discovered_tasks)
        self._discovered_tasks.clear()
        return count


# ── 从环境变量构建 DiscoveryManager ──

def build_discovery_manager_from_env() -> DiscoveryManager:
    """根据环境变量构建 DiscoveryManager"""
    manager = DiscoveryManager()

    # 文件扫描
    scan_dirs = os.getenv("DISCOVERY_SCAN_DIRS", "")
    if scan_dirs:
        dirs = [d.strip() for d in scan_dirs.split(",") if d.strip()]
        manager.register_source(FileScannerSource(scan_dirs=dirs))

    # Git 仓库
    git_repos = os.getenv("DISCOVERY_GIT_REPOS", "")
    if git_repos:
        repos = [r.strip() for r in git_repos.split(",") if r.strip()]
        manager.register_source(GitProjectSource(repo_dirs=repos))

    # 配置任务
    config_path = os.getenv("DISCOVERY_CONFIG_PATH")
    if config_path:
        manager.register_source(ConfigurableSource(config_path=config_path))

    # API 轮询
    api_url = os.getenv("DISCOVERY_API_URL")
    if api_url:
        poll_interval = int(os.getenv("DISCOVERY_API_POLL_INTERVAL", "60"))
        manager.register_source(APIPollingSource(api_url=api_url, poll_interval=poll_interval))

    # 关键词触发
    triggers_str = os.getenv("DISCOVERY_KEYWORD_TRIGGERS")
    if triggers_str:
        try:
            triggers = json.loads(triggers_str)
            manager.register_source(KeywordTriggerSource(triggers=triggers))
        except Exception:
            pass

    return manager
