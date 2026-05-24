"""Tests for skill_memory module"""

import pytest
import tempfile
import os

from backend.skill_memory import (
    SkillMemory,
    SkillTemplate,
    SkillStep,
    SkillStatus,
    SkillSource,
)


class TestSkillMemory:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.storage_path = os.path.join(self.temp_dir, "test_skills.json")
        self.memory = SkillMemory(storage_path=self.storage_path)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_skill(self):
        skill = SkillTemplate(
            name="test_skill",
            description="A test skill",
            trigger_keywords=["test", "example"],
            preferred_agents=["openclaw"],
        )

        created = self.memory.create_skill(skill)
        assert created.id == skill.id
        assert created.name == "test_skill"

    def test_get_skill(self):
        skill = SkillTemplate(name="test_skill")
        self.memory.create_skill(skill)

        retrieved = self.memory.get_skill(skill.id)
        assert retrieved is not None
        assert retrieved.name == "test_skill"

    def test_list_skills(self):
        self.memory.create_skill(SkillTemplate(name="skill1", status=SkillStatus.ACTIVE))
        self.memory.create_skill(SkillTemplate(name="skill2", status=SkillStatus.DRAFT))
        self.memory.create_skill(SkillTemplate(name="skill3", status=SkillStatus.ACTIVE))

        all_skills = self.memory.list_skills()
        assert len(all_skills) == 3

        active_skills = self.memory.list_skills(status=SkillStatus.ACTIVE)
        assert len(active_skills) == 2

    def test_match_skill(self):
        skill = SkillTemplate(
            name="web_scrape",
            trigger_keywords=["网页", "抓取", "scrape"],
            status=SkillStatus.ACTIVE,
        )
        self.memory.create_skill(skill)

        # 应该匹配
        matched = self.memory.match_skill("帮我抓取这个网页的内容")
        assert matched is not None
        assert matched.name == "web_scrape"

        # 不应该匹配
        matched = self.memory.match_skill("写一个Python脚本")
        assert matched is None

    def test_activate_disable(self):
        skill = SkillTemplate(name="test_skill", status=SkillStatus.DRAFT)
        self.memory.create_skill(skill)

        self.memory.activate_skill(skill.id)
        assert self.memory.get_skill(skill.id).status == SkillStatus.ACTIVE

        self.memory.disable_skill(skill.id)
        assert self.memory.get_skill(skill.id).status == SkillStatus.DISABLED

    def test_delete_skill(self):
        skill = SkillTemplate(name="test_skill")
        self.memory.create_skill(skill)

        assert self.memory.delete_skill(skill.id) is True
        assert self.memory.get_skill(skill.id) is None

    def test_skill_record_success(self):
        skill = SkillTemplate(name="test_skill")
        skill.record_success(10.0)

        assert skill.total_uses == 1
        assert skill.success_count == 1
        assert skill.avg_duration == 10.0

    def test_skill_record_failure(self):
        skill = SkillTemplate(name="test_skill")
        skill.record_failure("Connection error")

        assert skill.total_uses == 1
        assert skill.fail_count == 1
        assert "Connection error" in skill.failure_reasons

    def test_get_stats(self):
        self.memory.create_skill(SkillTemplate(name="skill1", status=SkillStatus.ACTIVE))
        self.memory.create_skill(SkillTemplate(name="skill2", status=SkillStatus.DRAFT))

        stats = self.memory.get_stats()
        assert stats["total_skills"] == 2
        assert stats["active_skills"] == 1
        assert stats["draft_skills"] == 1

    def test_persistence(self):
        skill = SkillTemplate(name="persistent_skill")
        self.memory.create_skill(skill)

        # 创建新的内存实例
        new_memory = SkillMemory(storage_path=self.storage_path)
        retrieved = new_memory.get_skill(skill.id)
        assert retrieved is not None
        assert retrieved.name == "persistent_skill"


class TestSkillTemplate:
    def test_to_dict(self):
        skill = SkillTemplate(
            name="test",
            description="Test skill",
            trigger_keywords=["test"],
            steps=[SkillStep(step_id=1, action="do something", agent="openclaw")],
        )

        d = skill.to_dict()
        assert d["name"] == "test"
        assert len(d["steps"]) == 1
        assert d["steps"][0]["action"] == "do something"

    def test_success_rate(self):
        skill = SkillTemplate(name="test")
        skill.total_uses = 10
        skill.success_count = 8

        assert skill.success_rate == 80.0

    def test_success_rate_zero_uses(self):
        skill = SkillTemplate(name="test")
        assert skill.success_rate == 0
