"""Skill and plugin management routes."""
import logging
import json
import re
import zipfile
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from backend.skill_memory import SkillMemory, SkillStatus, SkillSource, SkillTemplate
from backend.plugin_manager import PluginManager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["skills"])

_skill_install_lock = None  # Will be initialized in app.py


class SkillCreateRequestModel(BaseModel):
    name: str
    description: str = ""
    trigger_keywords: list[str] = []
    preferred_agents: list[str] = []
    required_plugins: list[str] = []
    tags: list[str] = []


def _parse_skill_md(skill_dir: Path) -> dict | None:
    """Parse skill info from SKILL.md frontmatter."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    try:
        content = skill_md.read_text("utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                import yaml
                meta = yaml.safe_load(parts[1])
                if meta:
                    result = dict(meta)
                    result["name"] = result.get("name", skill_dir.name)
                    return result
        return {"name": skill_dir.name, "description": content[:200]}
    except Exception:
        return {"name": skill_dir.name, "description": ""}


def _parse_plugin_manifest(plugin_dir: Path) -> dict | None:
    """Parse plugin manifest."""
    for name in ("manifest.json", "plugin.json"):
        manifest_file = plugin_dir / name
        if manifest_file.exists():
            try:
                return json.loads(manifest_file.read_text("utf-8"))
            except Exception:
                pass
    valid_dirs = {"tools", "routes", "skills", "agents", "commands", "providers", "extensions"}
    if any((plugin_dir / d).is_dir() for d in valid_dirs):
        return {"name": plugin_dir.name, "version": "0.0.1"}
    return None


@router.get("/skills")
def list_skills(
    skill_memory: SkillMemory,
    status: Optional[str] = None,
) -> list[dict]:
    """List all skills, optionally filtered by status."""
    try:
        skill_status = SkillStatus(status) if status else None
        return [s.to_dict() for s in skill_memory.list_skills(status=skill_status)]
    except Exception as e:
        logger.error(f"[skills] list error: {e}")
        return []


@router.get("/skills/stats")
def skill_stats(skill_memory: SkillMemory) -> dict:
    """Get skill statistics."""
    try:
        return skill_memory.get_stats()
    except Exception as e:
        logger.error(f"[skills] stats error: {e}")
        return {}


@router.get("/skills/{skill_id}")
def get_skill(skill_id: str, skill_memory: SkillMemory) -> dict:
    """Get skill details."""
    skill = skill_memory.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill.to_dict()


@router.post("/skills")
def create_skill(
    payload: SkillCreateRequestModel,
    skill_memory: SkillMemory,
) -> dict:
    """Create a new skill."""
    skill = SkillTemplate(
        name=payload.name,
        description=payload.description,
        trigger_keywords=payload.trigger_keywords,
        preferred_agents=payload.preferred_agents,
        required_plugins=payload.required_plugins,
        tags=payload.tags,
        status=SkillStatus.DRAFT,
        source=SkillSource.MANUAL,
    )
    created = skill_memory.create_skill(skill)
    return created.to_dict()


@router.post("/skills/{skill_id}/activate")
def activate_skill(skill_id: str, skill_memory: SkillMemory) -> dict:
    """Activate a skill."""
    ok = skill_memory.activate_skill(skill_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"ok": True}


@router.post("/skills/{skill_id}/disable")
def disable_skill(skill_id: str, skill_memory: SkillMemory) -> dict:
    """Disable a skill."""
    ok = skill_memory.disable_skill(skill_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"ok": True}


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: str, skill_memory: SkillMemory) -> dict:
    """Delete a skill."""
    ok = skill_memory.delete_skill(skill_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"ok": True}


@router.post("/skills/upload")
async def upload_skill(
    file: UploadFile = File(...),
    skill_memory: SkillMemory = None,
    data_dir: Path = None,
) -> dict:
    """Upload and install a skill from ZIP/.skill file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".zip", ".skill"):
        raise HTTPException(status_code=400, detail="仅支持 .zip 和 .skill 文件")

    user_skills_dir = data_dir / "user_skills"
    user_skills_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="skill-install-"))

    try:
        zip_path = tmp_dir / file.filename
        with open(zip_path, "wb") as f:
            content = await file.read()
            f.write(content)

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)

        skill_dir = None
        if (tmp_dir / "SKILL.md").exists():
            skill_dir = tmp_dir
        else:
            for entry in tmp_dir.iterdir():
                if entry.is_dir() and not entry.name.startswith(".") and (entry / "SKILL.md").exists():
                    skill_dir = entry
                    break

        if not skill_dir:
            raise HTTPException(status_code=400, detail="ZIP 中未找到 SKILL.md")

        skill_info = _parse_skill_md(skill_dir)
        if not skill_info:
            raise HTTPException(status_code=400, detail="SKILL.md 解析失败")

        skill_name = skill_info.get("name", skill_dir.name)
        safe_name = re.sub(r'[^\w\-]', '_', skill_name).strip('_').lower()
        if not safe_name:
            safe_name = skill_dir.name

        dst_dir = user_skills_dir / safe_name
        if dst_dir.exists():
            shutil.rmtree(dst_dir)
        shutil.copytree(skill_dir, dst_dir)

        skill = SkillTemplate(
            name=safe_name,
            description=skill_info.get("description", ""),
            status=SkillStatus.ACTIVE,
            source=SkillSource.IMPORTED,
            tags=["uploaded"],
            metadata={"source_file": file.filename, "skill_dir": str(dst_dir)},
        )
        created = skill_memory.create_skill(skill)

        logger.info(f"[upload] 技能已安装: {safe_name} from {file.filename}")
        return {"ok": True, "skill": created.to_dict(), "message": f"技能 {safe_name} 安装成功"}

    except HTTPException:
        raise
    except Exception as err:
        logger.error(f"[upload] 技能安装失败: {err}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"安装失败: {err}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.get("/plugins")
def list_plugins(plugin_manager: PluginManager) -> list[dict]:
    """List all plugins."""
    try:
        return [p.to_dict() for p in plugin_manager.list_plugins()]
    except Exception as e:
        logger.error(f"[plugins] list error: {e}")
        return []


@router.post("/plugins/{plugin_id}/activate")
def activate_plugin(plugin_id: str, plugin_manager: PluginManager) -> dict:
    """Activate a plugin."""
    ok = plugin_manager.enable_plugin(plugin_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return {"ok": True}


@router.post("/plugins/{plugin_id}/disable")
def disable_plugin(plugin_id: str, plugin_manager: PluginManager) -> dict:
    """Disable a plugin."""
    ok = plugin_manager.disable_plugin(plugin_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return {"ok": True}


@router.get("/plugins/capabilities")
def capability_map(plugin_manager: PluginManager) -> dict:
    """Get all plugin capabilities."""
    try:
        return plugin_manager.get_all_capabilities()
    except Exception as e:
        logger.error(f"[plugins] capabilities error: {e}")
        return {}