"""__init__.py - Centralized route registration."""
from backend.routes.tasks import router as tasks_router
from backend.routes.bridge import router as bridge_router
from backend.routes.skills import router as skills_router
from backend.routes.agents import router as agents_router
from backend.routes.monitoring import router as monitoring_router

__all__ = [
    "tasks_router",
    "bridge_router",
    "skills_router",
    "agents_router",
    "monitoring_router",
]