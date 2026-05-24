import sys, os, asyncio
sys.path.insert(0, '.')
os.chdir('.')

from backend.orchestration.execution_plan import ExecutionPlan
from backend.orchestration.orchestrator import MultiAgentOrchestrator
from backend.orchestration.aggregator import ResultAggregator
from backend.core.router import AgentRouter
from backend.adapters.openclaw_adapter import OpenClawAdapter
from backend.adapters.openhanako_adapter import OpenHanakoAdapter
from backend.adapters.hermes_adapter import HermesAdapter

print('All imports OK!')

agent_router = AgentRouter()
agent_router.register(OpenClawAdapter())
agent_router.register(OpenHanakoAdapter())
agent_router.register(HermesAdapter())
print('Agents registered: %s' % list(agent_router.agents.keys()))
print('get_agent test: openclaw=%s, hanako=%s, hermes=%s' % (
    agent_router.get_agent('openclaw') is not None,
    agent_router.get_agent('hanako') is not None,
    agent_router.get_agent('hermes') is not None,
))

aggregator = ResultAggregator()
orchestrator = MultiAgentOrchestrator(agent_router, aggregator)

async def run_all_demos():
    results = []

    plan = ExecutionPlan.single('demo_1', 'hanako', 'chat with me')
    result = await orchestrator.execute(plan)
    status = 'PASS' if result.success else 'FAIL'
    print('Demo 1 (Single-Hanako): [%s] %s' % (status, result.status))
    results.append(('Demo 1', result))

    plan2 = ExecutionPlan.single('demo_2', 'openclaw', 'fix the bug')
    result2 = await orchestrator.execute(plan2)
    status = 'PASS' if result2.success else 'FAIL'
    print('Demo 2 (Single-OpenClaw): [%s] %s' % (status, result2.status))
    results.append(('Demo 2', result2))

    plan3 = ExecutionPlan.single('demo_3', 'hermes', 'plan project roadmap')
    result3 = await orchestrator.execute(plan3)
    status = 'PASS' if result3.success else 'FAIL'
    print('Demo 3 (Single-Hermes): [%s] %s' % (status, result3.status))
    results.append(('Demo 3', result3))

    plan4 = ExecutionPlan.pipeline('demo_4', 'analyze and summarize', [
        ('hermes', 'analyze the project'),
        ('hanako', 'rewrite in friendly tone'),
    ])
    result4 = await orchestrator.execute(plan4)
    status = 'PASS' if result4.success else 'FAIL'
    print('Demo 4 (Pipeline): [%s] %s' % (status, result4.status))
    results.append(('Demo 4', result4))

    plan5 = ExecutionPlan.parallel('demo_5', 'full project check', [
        ('openclaw', 'check code structure'),
        ('hermes', 'analyze project roadmap'),
        ('hanako', 'make it user friendly'),
    ])
    result5 = await orchestrator.execute(plan5)
    status = 'PASS' if result5.success else 'FAIL'
    print('Demo 5 (Parallel): [%s] %s' % (status, result5.status))
    results.append(('Demo 5', result5))

    print('\n' + '='*60)
    print('SUMMARY')
    print('='*60)
    for name, r in results:
        s = 'PASS' if r.success else 'FAIL'
        print('%s: [%s] %s' % (name, s, r.status))

asyncio.run(run_all_demos())
