from backend.models import AgentChoice, RoutingDecision


HERMES_KEYWORDS = ("research", "summary", "summarize", "analysis")
OPENCLAW_KEYWORDS = ("implement", "code", "fix", "build")
OPENHANAKO_KEYWORDS = ("wechat", "微信", "bridge", "桥接", "desktop", "桌面", "chat", "聊天")
ILIYA_KEYWORDS = ("调度", "分发", "编排", "协调", "指挥", "执行命令", "运行命令", "iliya", "伊利亚", "schedule", "dispatch", "orchestrate")


def route_task(goal: str, requested_agent: AgentChoice) -> RoutingDecision:
    if requested_agent != AgentChoice.AUTO:
        return RoutingDecision(
            requested_agent=requested_agent,
            selected_agent=requested_agent,
            routing_reason=f"Explicit agent selection: {requested_agent.value}",
        )

    lowered_goal = goal.lower()

    for keyword in ILIYA_KEYWORDS:
        if keyword in lowered_goal:
            return RoutingDecision(
                requested_agent=requested_agent,
                selected_agent=AgentChoice.ILIYA,
                routing_reason=f"Auto-routed to iliya because goal matched keyword '{keyword}'",
            )

    for keyword in OPENHANAKO_KEYWORDS:
        if keyword in lowered_goal:
            return RoutingDecision(
                requested_agent=requested_agent,
                selected_agent=AgentChoice.OPENHANAKO,
                routing_reason=f"Auto-routed to openhanako because goal matched keyword '{keyword}'",
            )

    for keyword in HERMES_KEYWORDS:
        if keyword in lowered_goal:
            return RoutingDecision(
                requested_agent=requested_agent,
                selected_agent=AgentChoice.HERMES,
                routing_reason=f"Auto-routed to hermes because goal matched keyword '{keyword}'",
            )

    for keyword in OPENCLAW_KEYWORDS:
        if keyword in lowered_goal:
            return RoutingDecision(
                requested_agent=requested_agent,
                selected_agent=AgentChoice.OPENCLAW,
                routing_reason=f"Auto-routed to openclaw because goal matched keyword '{keyword}'",
            )

    return RoutingDecision(
        requested_agent=requested_agent,
        selected_agent=AgentChoice.HERMES,
        routing_reason="Auto-routed to hermes as the default fallback for non-specific goals",
    )
