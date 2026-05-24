"""
task_store.py - 增强版任务存储

提供：
1. 实时状态更新
2. 任务日志聚合
3. 版本管理（重试历史）
4. 任务血缘追踪
"""

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class TaskStatus:
    """任务状态常量"""
    CREATED = "created"
    ROUTED = "routed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskState:
    """任务状态快照"""
    task_id: str
    status: str
    timestamp: float
    agent: Optional[str] = None
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "timestamp": self.timestamp,
            "agent": self.agent,
            "message": self.message,
        }


@dataclass
class TaskLog:
    """任务执行日志"""
    log_id: str
    task_id: str
    level: str  # info, warning, error
    message: str
    timestamp: float
    agent: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "log_id": self.log_id,
            "task_id": self.task_id,
            "level": self.level,
            "message": self.message,
            "timestamp": self.timestamp,
            "agent": self.agent,
            "metadata": self.metadata,
        }


@dataclass
class TaskVersion:
    """任务版本（用于重试历史）"""
    version_id: str
    task_id: str
    version_number: int
    status: str
    result: Optional[str]
    error: Optional[str]
    created_at: float
    duration: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version_id": self.version_id,
            "task_id": self.task_id,
            "version_number": self.version_number,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "duration": self.duration,
        }


@dataclass
class TaskInfo:
    """任务完整信息"""
    task_id: str
    user_id: str
    source: str
    content: str
    task_type: str
    project: Optional[str]
    target_agent: Optional[str]
    status: str
    result: Optional[str]
    error: Optional[str]
    created_at: float
    updated_at: float
    states: List[TaskState] = field(default_factory=list)
    logs: List[TaskLog] = field(default_factory=list)
    versions: List[TaskVersion] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "source": self.source,
            "content": self.content,
            "task_type": self.task_type,
            "project": self.project,
            "target_agent": self.target_agent,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "states": [s.to_dict() for s in self.states],
            "logs": [l.to_dict() for l in self.logs],
            "versions": [v.to_dict() for v in self.versions],
        }


class EnhancedTaskStore:
    """
    增强版任务存储

    支持：
    - 任务状态实时追踪
    - 执行日志聚合
    - 版本管理（重试历史）
    - 任务血缘追踪
    """

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """确保数据库表存在"""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(self.database_path) as conn:
            # 主任务表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    task_type TEXT DEFAULT 'general',
                    project TEXT,
                    target_agent TEXT,
                    status TEXT NOT NULL DEFAULT 'created',
                    result TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)
            
            # 任务状态历史表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_states (
                    state_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    agent TEXT,
                    message TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                )
            """)
            
            # 任务日志表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_logs (
                    log_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    agent TEXT,
                    metadata TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                )
            """)
            
            # 任务版本表（重试历史）
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_versions (
                    version_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    version_number INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    duration REAL,
                    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
                )
            """)
            
            # 任务血缘表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_lineage (
                    lineage_id TEXT PRIMARY KEY,
                    parent_task_id TEXT NOT NULL,
                    child_task_id TEXT NOT NULL,
                    relationship TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (parent_task_id) REFERENCES tasks(task_id),
                    FOREIGN KEY (child_task_id) REFERENCES tasks(task_id)
                )
            """)
            
            # 创建索引
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_states_task ON task_states(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_logs_task ON task_logs(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_versions_task ON task_versions(task_id)")

    def create_task(
        self,
        user_id: str,
        source: str,
        content: str,
        task_type: str = "general",
        project: Optional[str] = None,
    ) -> str:
        """创建新任务"""
        task_id = str(uuid4())
        now = time.time()
        
        with sqlite3.connect(self.database_path) as conn:
            conn.execute(
                """
                INSERT INTO tasks 
                (task_id, user_id, source, content, task_type, project, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, user_id, source, content, task_type, project, TaskStatus.CREATED, now, now)
            )
            
            # 记录初始状态
            self._add_state(conn, task_id, TaskStatus.CREATED, "任务已创建")
        
        logger.info(f"[task-store] 创建任务: {task_id}")
        return task_id

    def _add_state(
        self,
        conn: sqlite3.Connection,
        task_id: str,
        status: str,
        message: Optional[str] = None,
        agent: Optional[str] = None,
    ) -> None:
        """添加任务状态"""
        state_id = str(uuid4())
        now = time.time()
        
        conn.execute(
            """
            INSERT INTO task_states (state_id, task_id, status, timestamp, agent, message)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (state_id, task_id, status, now, agent, message)
        )
        
        # 更新任务表
        conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
            (status, now, task_id)
        )

    def add_log(
        self,
        task_id: str,
        level: str,
        message: str,
        agent: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        """添加任务日志"""
        log_id = str(uuid4())
        now = time.time()
        
        with sqlite3.connect(self.database_path) as conn:
            conn.execute(
                """
                INSERT INTO task_logs (log_id, task_id, level, message, timestamp, agent, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (log_id, task_id, level, message, now, agent, json.dumps(metadata or {}))
            )

    def update_status(
        self,
        task_id: str,
        status: str,
        message: Optional[str] = None,
        agent: Optional[str] = None,
    ) -> None:
        """更新任务状态"""
        with sqlite3.connect(self.database_path) as conn:
            self._add_state(conn, task_id, status, message, agent)
        
        logger.info(f"[task-store] 任务状态更新: {task_id} -> {status}")

    def complete_task(
        self,
        task_id: str,
        result: str,
        agent: Optional[str] = None,
    ) -> None:
        """标记任务完成"""
        now = time.time()
        
        with sqlite3.connect(self.database_path) as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, result = ?, updated_at = ? WHERE task_id = ?",
                (TaskStatus.COMPLETED, result, now, task_id)
            )
            self._add_state(conn, task_id, TaskStatus.COMPLETED, "任务完成", agent)
        
        logger.info(f"[task-store] 任务完成: {task_id}")

    def fail_task(
        self,
        task_id: str,
        error: str,
        agent: Optional[str] = None,
    ) -> None:
        """标记任务失败"""
        now = time.time()
        
        with sqlite3.connect(self.database_path) as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, error = ?, updated_at = ? WHERE task_id = ?",
                (TaskStatus.FAILED, error, now, task_id)
            )
            self._add_state(conn, task_id, TaskStatus.FAILED, f"任务失败: {error}", agent)
        
        logger.warning(f"[task-store] 任务失败: {task_id} - {error}")

    def add_version(
        self,
        task_id: str,
        status: str,
        result: Optional[str] = None,
        error: Optional[str] = None,
        duration: float = 0.0,
    ) -> str:
        """添加任务版本（重试历史）"""
        version_id = str(uuid4())
        now = time.time()
        
        with sqlite3.connect(self.database_path) as conn:
            # 获取当前版本号
            cursor = conn.execute(
                "SELECT MAX(version_number) FROM task_versions WHERE task_id = ?",
                (task_id,)
            )
            max_version = cursor.fetchone()[0] or 0
            version_number = max_version + 1
            
            conn.execute(
                """
                INSERT INTO task_versions 
                (version_id, task_id, version_number, status, result, error, created_at, duration)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (version_id, task_id, version_number, status, result, error, now, duration)
            )
        
        logger.info(f"[task-store] 添加任务版本: {task_id} v{version_number}")
        return version_id

    def add_lineage(
        self,
        parent_task_id: str,
        child_task_id: str,
        relationship: str,
    ) -> None:
        """添加任务血缘关系"""
        lineage_id = str(uuid4())
        now = time.time()
        
        with sqlite3.connect(self.database_path) as conn:
            conn.execute(
                """
                INSERT INTO task_lineage (lineage_id, parent_task_id, child_task_id, relationship, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (lineage_id, parent_task_id, child_task_id, relationship, now)
            )
        
        logger.debug(f"[task-store] 添加血缘: {parent_task_id} -> {child_task_id} ({relationship})")

    def get_task_info(self, task_id: str) -> Optional[TaskInfo]:
        """获取任务完整信息"""
        with sqlite3.connect(self.database_path) as conn:
            conn.row_factory = sqlite3.Row
            
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE task_id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            # 获取状态历史
            states = []
            for state_row in conn.execute(
                "SELECT * FROM task_states WHERE task_id = ? ORDER BY timestamp",
                (task_id,)
            ):
                states.append(TaskState(
                    state_id=state_row["state_id"],
                    task_id=state_row["task_id"],
                    status=state_row["status"],
                    timestamp=state_row["timestamp"],
                    agent=state_row["agent"],
                    message=state_row["message"],
                ))
            
            # 获取日志
            logs = []
            for log_row in conn.execute(
                "SELECT * FROM task_logs WHERE task_id = ? ORDER BY timestamp",
                (task_id,)
            ):
                logs.append(TaskLog(
                    log_id=log_row["log_id"],
                    task_id=log_row["task_id"],
                    level=log_row["level"],
                    message=log_row["message"],
                    timestamp=log_row["timestamp"],
                    agent=log_row["agent"],
                    metadata=json.loads(log_row["metadata"] or "{}"),
                ))
            
            # 获取版本
            versions = []
            for version_row in conn.execute(
                "SELECT * FROM task_versions WHERE task_id = ? ORDER BY version_number",
                (task_id,)
            ):
                versions.append(TaskVersion(
                    version_id=version_row["version_id"],
                    task_id=version_row["task_id"],
                    version_number=version_row["version_number"],
                    status=version_row["status"],
                    result=version_row["result"],
                    error=version_row["error"],
                    created_at=version_row["created_at"],
                    duration=version_row["duration"],
                ))
            
            return TaskInfo(
                task_id=row["task_id"],
                user_id=row["user_id"],
                source=row["source"],
                content=row["content"],
                task_type=row["task_type"],
                project=row["project"],
                target_agent=row["target_agent"],
                status=row["status"],
                result=row["result"],
                error=row["error"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                states=states,
                logs=logs,
                versions=versions,
            )

    def list_tasks(
        self,
        user_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict]:
        """列出任务"""
        query = "SELECT * FROM tasks WHERE 1=1"
        params = []
        
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        with sqlite3.connect(self.database_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_lineage(self, task_id: str) -> Dict[str, Any]:
        """获取任务血缘关系"""
        with sqlite3.connect(self.database_path) as conn:
            conn.row_factory = sqlite3.Row
            
            parents = []
            for row in conn.execute(
                """
                SELECT t.*, l.relationship FROM tasks t
                JOIN task_lineage l ON t.task_id = l.parent_task_id
                WHERE l.child_task_id = ?
                """,
                (task_id,)
            ):
                parents.append({
                    "task_id": row["task_id"],
                    "content": row["content"],
                    "status": row["status"],
                    "relationship": row["relationship"],
                })
            
            children = []
            for row in conn.execute(
                """
                SELECT t.*, l.relationship FROM tasks t
                JOIN task_lineage l ON t.task_id = l.child_task_id
                WHERE l.parent_task_id = ?
                """,
                (task_id,)
            ):
                children.append({
                    "task_id": row["task_id"],
                    "content": row["content"],
                    "status": row["status"],
                    "relationship": row["relationship"],
                })
            
            return {
                "task_id": task_id,
                "parents": parents,
                "children": children,
            }

    def get_stats(self) -> Dict[str, Any]:
        """获取任务统计信息"""
        with sqlite3.connect(self.database_path) as conn:
            conn.row_factory = sqlite3.Row
            
            # 总任务数
            total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            
            # 各状态数量
            status_counts = {}
            for row in conn.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status"):
                status_counts[row["status"]] = row[1]
            
            # 平均执行时长
            avg_duration_result = conn.execute(
                "SELECT AVG(duration) FROM task_versions WHERE duration > 0"
            ).fetchone()[0]
            
            return {
                "total_tasks": total,
                "by_status": status_counts,
                "avg_duration": round(avg_duration_result or 0, 2),
            }
