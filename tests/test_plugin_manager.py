"""Tests for plugin_manager module"""

import pytest
import tempfile
import os

from backend.plugin_manager import (
    PluginManager,
    PluginRecord,
    PluginCapability,
    PluginStatus,
    SafeLevel,
)


class TestPluginManager:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = os.path.join(self.temp_dir, "test_plugins.json")
        self.manager = PluginManager(storage_path=self.storage_path)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_register_plugin(self):
        plugin = PluginRecord(
            name="test_plugin",
            display_name="Test Plugin",
            capabilities=[
                PluginCapability(name="fetch", description="Fetch web pages"),
            ],
        )

        created = self.manager.register_plugin(plugin)
        assert created.name == "test_plugin"

    def test_get_plugin(self):
        plugin = PluginRecord(name="test_plugin")
        self.manager.register_plugin(plugin)

        retrieved = self.manager.get_plugin(plugin.id)
        assert retrieved is not None
        assert retrieved.name == "test_plugin"

    def test_get_plugin_by_name(self):
        plugin = PluginRecord(name="my_plugin")
        self.manager.register_plugin(plugin)

        retrieved = self.manager.get_plugin_by_name("my_plugin")
        assert retrieved is not None

    def test_list_plugins(self):
        self.manager.register_plugin(PluginRecord(name="p1", status=PluginStatus.ACTIVE))
        self.manager.register_plugin(PluginRecord(name="p2", status=PluginStatus.INACTIVE))

        all_plugins = self.manager.list_plugins()
        assert len(all_plugins) == 2

        active = self.manager.list_plugins(status=PluginStatus.ACTIVE)
        assert len(active) == 1

    def test_find_plugins_for_capability(self):
        plugin = PluginRecord(
            name="web_tool",
            capabilities=[PluginCapability(name="fetch")],
            status=PluginStatus.ACTIVE,
        )
        self.manager.register_plugin(plugin)

        results = self.manager.find_plugins_for_capability("fetch")
        assert len(results) == 1
        assert results[0].name == "web_tool"

    def test_find_plugins_with_agent_filter(self):
        plugin = PluginRecord(
            name="restricted_tool",
            allowed_agents=["hermes"],
            capabilities=[PluginCapability(name="fetch")],
            status=PluginStatus.ACTIVE,
        )
        self.manager.register_plugin(plugin)

        # hermes 应该能找到
        results = self.manager.find_plugins_for_capability("fetch", agent="hermes")
        assert len(results) == 1

        # openclaw 不应该找到
        results = self.manager.find_plugins_for_capability("fetch", agent="openclaw")
        assert len(results) == 0

    def test_get_fallback_chain(self):
        plugin1 = PluginRecord(
            name="primary",
            fallback_plugins=["secondary"],
            status=PluginStatus.ACTIVE,
        )
        plugin2 = PluginRecord(
            name="secondary",
            status=PluginStatus.ACTIVE,
        )
        self.manager.register_plugin(plugin1)
        self.manager.register_plugin(plugin2)

        chain = self.manager.get_fallback_chain("primary")
        assert len(chain) == 1
        assert chain[0].name == "secondary"

    def test_get_all_capabilities(self):
        self.manager.register_plugin(PluginRecord(
            name="tool1",
            capabilities=[
                PluginCapability(name="fetch"),
                PluginCapability(name="parse"),
            ],
            status=PluginStatus.ACTIVE,
        ))
        self.manager.register_plugin(PluginRecord(
            name="tool2",
            capabilities=[PluginCapability(name="fetch")],
            status=PluginStatus.ACTIVE,
        ))

        caps = self.manager.get_all_capabilities()
        assert "fetch" in caps
        assert len(caps["fetch"]) == 2
        assert "parse" in caps
        assert len(caps["parse"]) == 1

    def test_enable_disable(self):
        plugin = PluginRecord(name="test", status=PluginStatus.INACTIVE)
        self.manager.register_plugin(plugin)

        self.manager.enable_plugin(plugin.id)
        assert self.manager.get_plugin(plugin.id).status == PluginStatus.ACTIVE

        self.manager.disable_plugin(plugin.id)
        assert self.manager.get_plugin(plugin.id).status == PluginStatus.INACTIVE

    def test_unregister_plugin(self):
        plugin = PluginRecord(name="test")
        self.manager.register_plugin(plugin)

        assert self.manager.unregister_plugin(plugin.id) is True
        assert self.manager.get_plugin(plugin.id) is None

    def test_get_stats(self):
        self.manager.register_plugin(PluginRecord(name="p1", status=PluginStatus.ACTIVE))
        self.manager.register_plugin(PluginRecord(name="p2", status=PluginStatus.ACTIVE))

        stats = self.manager.get_stats()
        assert stats["total_plugins"] == 2
        assert stats["active_plugins"] == 2

    def test_persistence(self):
        plugin = PluginRecord(name="persistent")
        self.manager.register_plugin(plugin)

        new_manager = PluginManager(storage_path=self.storage_path)
        retrieved = new_manager.get_plugin_by_name("persistent")
        assert retrieved is not None


class TestPluginRecord:
    def test_has_capability(self):
        plugin = PluginRecord(
            capabilities=[
                PluginCapability(name="fetch"),
                PluginCapability(name="parse"),
            ]
        )

        assert plugin.has_capability("fetch") is True
        assert plugin.has_capability("download") is False

    def test_record_use(self):
        plugin = PluginRecord(name="test")
        plugin.record_use(success=True)

        assert plugin.total_uses == 1
        assert plugin.success_count == 1

        plugin.record_use(success=False, error="Timeout")
        assert plugin.total_uses == 2
        assert plugin.fail_count == 1
        assert len(plugin.failure_history) == 1

    def test_to_dict(self):
        plugin = PluginRecord(
            name="test",
            display_name="Test Plugin",
            capabilities=[PluginCapability(name="fetch")],
        )

        d = plugin.to_dict()
        assert d["name"] == "test"
        assert d["display_name"] == "Test Plugin"
        assert "fetch" in d["capability_names"]
