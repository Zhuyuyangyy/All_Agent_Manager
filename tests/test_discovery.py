"""Tests for project_discovery module"""

import json
import tempfile
from pathlib import Path

import pytest

from backend.project_discovery import (
    ConfigurableSource,
    DiscoveryManager,
    FileScannerSource,
    GitProjectSource,
    TaskPriority,
    TaskType,
)


class TestFileScannerSource:
    def test_scan_todo_comments(self, tmp_path):
        # 创建包含 TODO 的测试文件
        test_file = tmp_path / "test.py"
        test_file.write_text("# TODO: implement this function\n# FIXME: bug here\nprint('hello')")

        scanner = FileScannerSource(scan_dirs=[str(tmp_path)])
        tasks = scanner.discover()

        assert len(tasks) == 2
        assert any("implement" in t.goal for t in tasks)
        assert any("bug" in t.goal for t in tasks)

    def test_scan_empty_directory(self, tmp_path):
        scanner = FileScannerSource(scan_dirs=[str(tmp_path)])
        tasks = scanner.discover()
        assert len(tasks) == 0

    def test_excluded_directories(self, tmp_path):
        # 创建 node_modules 目录（应该被排除）
        node_modules = tmp_path / "node_modules" / "package"
        node_modules.mkdir(parents=True)
        (node_modules / "index.js").write_text("// TODO: test")

        scanner = FileScannerSource(scan_dirs=[str(tmp_path)])
        tasks = scanner.discover()
        assert len(tasks) == 0

    def test_disabled_when_no_dirs(self):
        scanner = FileScannerSource(scan_dirs=[])
        assert scanner.is_enabled() is False

    def test_classify_todo(self):
        scanner = FileScannerSource()
        assert scanner._classify_todo("fix the bug") == TaskType.BUG_FIX
        assert scanner._classify_todo("add new feature") == TaskType.FEATURE
        assert scanner._classify_todo("research this topic") == TaskType.RESEARCH
        assert scanner._classify_todo("update documentation") == TaskType.DOCUMENTATION
        assert scanner._classify_todo("something else") == TaskType.CUSTOM


class TestConfigurableSource:
    def test_load_valid_config(self, tmp_path):
        config_file = tmp_path / "tasks.json"
        config_file.write_text(json.dumps([
            {"goal": "Task 1", "type": "feature", "priority": "high", "agent": "openclaw"},
            {"goal": "Task 2", "type": "research", "priority": "normal"},
        ]))

        source = ConfigurableSource(config_path=str(config_file))
        tasks = source.discover()

        assert len(tasks) == 2
        assert tasks[0].goal == "Task 1"
        assert tasks[0].task_type == TaskType.FEATURE
        assert tasks[0].priority == TaskPriority.HIGH

    def test_load_invalid_config(self, tmp_path):
        config_file = tmp_path / "tasks.json"
        config_file.write_text("not valid json")

        source = ConfigurableSource(config_path=str(config_file))
        tasks = source.discover()
        assert len(tasks) == 0

    def test_disabled_when_no_path(self):
        source = ConfigurableSource(config_path=None)
        assert source.is_enabled() is False


class TestDiscoveryManager:
    def test_register_and_discover(self, tmp_path):
        manager = DiscoveryManager()

        # 注册一个文件扫描器
        test_file = tmp_path / "test.py"
        test_file.write_text("# TODO: test task")

        scanner = FileScannerSource(scan_dirs=[str(tmp_path)])
        manager.register_source(scanner)

        # 扫描
        tasks = manager.scan_all()
        assert len(tasks) == 1

    def test_deduplication(self, tmp_path):
        manager = DiscoveryManager()

        test_file = tmp_path / "test.py"
        test_file.write_text("# TODO: test task")

        scanner = FileScannerSource(scan_dirs=[str(tmp_path)])
        manager.register_source(scanner)

        # 多次扫描，应该只返回一次
        tasks1 = manager.scan_all()
        tasks2 = manager.scan_all()

        assert len(tasks1) == 1
        assert len(tasks2) == 0  # 第二次扫描没有新任务

    def test_mark_task_taken(self, tmp_path):
        manager = DiscoveryManager()

        test_file = tmp_path / "test.py"
        test_file.write_text("# TODO: test task")

        scanner = FileScannerSource(scan_dirs=[str(tmp_path)])
        manager.register_source(scanner)

        manager.scan_all()
        assert len(manager.get_pending_tasks()) == 1

        task_id = manager.get_pending_tasks()[0].id
        manager.mark_task_taken(task_id)
        assert len(manager.get_pending_tasks()) == 0

    def test_clear_all(self, tmp_path):
        manager = DiscoveryManager()

        test_file = tmp_path / "test.py"
        test_file.write_text("# TODO: task1\n# TODO: task2")

        scanner = FileScannerSource(scan_dirs=[str(tmp_path)])
        manager.register_source(scanner)

        manager.scan_all()
        assert len(manager.get_pending_tasks()) == 2

        count = manager.clear_all()
        assert count == 2
        assert len(manager.get_pending_tasks()) == 0
