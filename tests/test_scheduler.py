from backend.models import AgentChoice
from backend.scheduler import route_task


def test_route_task_preserves_explicit_agent_choice():
    decision = route_task(
        goal="Implement the dispatcher API",
        requested_agent=AgentChoice.OPENCLAW,
    )

    assert decision.selected_agent == AgentChoice.OPENCLAW
    assert "explicit" in decision.routing_reason.lower()


def test_route_task_uses_keyword_heuristics_for_auto_mode():
    research_decision = route_task(
        goal="Research the market and summarize findings",
        requested_agent=AgentChoice.AUTO,
    )
    coding_decision = route_task(
        goal="Fix the failing build and implement the API",
        requested_agent=AgentChoice.AUTO,
    )
    fallback_decision = route_task(
        goal="Help me move this task forward",
        requested_agent=AgentChoice.AUTO,
    )

    assert research_decision.selected_agent == AgentChoice.HERMES
    assert "research" in research_decision.routing_reason.lower()
    assert coding_decision.selected_agent == AgentChoice.OPENCLAW
    assert "code" in coding_decision.routing_reason.lower() or "implement" in coding_decision.routing_reason.lower()
    assert fallback_decision.selected_agent == AgentChoice.HERMES
