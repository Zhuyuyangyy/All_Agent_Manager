"""
Performance Benchmarks for All Agent Manager
=============================================

This module contains benchmarks for measuring the performance of key
operations in the All Agent Manager application.

Run with: python -m pytest tests/test_performance_benchmarks.py -v
Or: python -m backend.benchmarks
"""
import asyncio
import time
import statistics
from typing import List, Callable, Any
from dataclasses import dataclass
from contextlib import asynccontextmanager

# Simulated data for benchmarks
SAMPLE_TASKS = [
    {"goal": "Write a simple REST API endpoint", "requested_agent": "auto"},
    {"goal": "Debug memory leak in worker process", "requested_agent": "openclaw"},
    {"goal": "Analyze latest market trends", "requested_agent": "hermes"},
    {"goal": "Create documentation for module X", "requested_agent": "auto"},
    {"goal": "Optimize database queries", "requested_agent": "openclaw"},
]


@dataclass
class BenchmarkResult:
    """Result of a benchmark run."""
    name: str
    iterations: int
    total_time: float
    avg_time: float
    min_time: float
    max_time: float
    std_dev: float
    ops_per_second: float

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "iterations": self.iterations,
            "total_time_ms": self.total_time * 1000,
            "avg_time_ms": self.avg_time * 1000,
            "min_time_ms": self.min_time * 1000,
            "max_time_ms": self.max_time * 1000,
            "std_dev_ms": self.std_dev * 1000,
            "ops_per_second": self.ops_per_second,
        }


def benchmark(name: str, fn: Callable, iterations: int = 100) -> BenchmarkResult:
    """Run a synchronous benchmark."""
    times: List[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    total = sum(times)
    return BenchmarkResult(
        name=name,
        iterations=iterations,
        total_time=total,
        avg_time=total / iterations,
        min_time=min(times),
        max_time=max(times),
        std_dev=statistics.stdev(times) if len(times) > 1 else 0,
        ops_per_second=iterations / total if total > 0 else 0,
    )


async def benchmark_async(
    name: str,
    fn: Callable,
    iterations: int = 100,
) -> BenchmarkResult:
    """Run an async benchmark."""
    times: List[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        await fn()
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    total = sum(times)
    return BenchmarkResult(
        name=name,
        iterations=iterations,
        total_time=total,
        avg_time=total / iterations,
        min_time=min(times),
        max_time=max(times),
        std_dev=statistics.stdev(times) if len(times) > 1 else 0,
        ops_per_second=iterations / total if total > 0 else 0,
    )


def benchmark_routing_simulation(iterations: int = 100) -> BenchmarkResult:
    """Benchmark task routing logic."""
    def route_task_simulated():
        import random
        goals = [t["goal"] for t in SAMPLE_TASKS]
        goal = random.choice(goals)

        # Simple routing simulation
        if "write" in goal.lower() or "create" in goal.lower():
            agent = "openclaw"
        elif "debug" in goal.lower() or "optimize" in goal.lower():
            agent = "openclaw"
        elif "analyze" in goal.lower() or "research" in goal.lower():
            agent = "hermes"
        else:
            agent = "auto"
        return agent

    return benchmark("Task Routing", route_task_simulated, iterations)


def benchmark_task_serialization(iterations: int = 1000) -> BenchmarkResult:
    """Benchmark task object serialization."""
    import json
    from backend.models import TaskCreate

    task = TaskCreate(goal="Test task for benchmark", requested_agent="auto")

    def serialize_task():
        return json.dumps(task.__dict__)

    return benchmark("Task Serialization", serialize_task, iterations)


async def benchmark_agent_dispatch_simulation(iterations: int = 50) -> BenchmarkResult:
    """Benchmark simulated agent dispatch."""
    async def dispatch_simulated():
        # Simulate async network delay
        await asyncio.sleep(0.001)  # 1ms simulated delay
        return {"status": "success", "agent": "openclaw"}

    return await benchmark_async("Agent Dispatch (simulated)", dispatch_simulated, iterations)


async def benchmark_event_bus_publish(iterations: int = 1000) -> BenchmarkResult:
    """Benchmark event bus publish operations."""
    from backend.event_bus import EventBus

    event_bus = EventBus()
    received = []

    @event_bus.on("benchmark_event")
    async def handler(data):
        received.append(data)

    async def publish_event():
        await event_bus.publish("benchmark_event", {"test": "data"})

    return await benchmark_async("Event Bus Publish", publish_event, iterations)


def benchmark_scheduler_scoring(iterations: int = 200) -> BenchmarkResult:
    """Benchmark task scoring in scheduler."""
    import random

    def score_task():
        # Simulate multi-factor scoring
        factors = {
            "complexity": random.uniform(0, 1),
            "urgency": random.uniform(0, 1),
            "cost": random.uniform(0, 1),
            "agent_availability": random.uniform(0, 1),
        }
        # Weighted scoring
        score = (
            factors["complexity"] * 0.2 +
            factors["urgency"] * 0.3 +
            factors["cost"] * 0.2 +
            factors["agent_availability"] * 0.3
        )
        return score

    return benchmark("Scheduler Scoring", score_task, iterations)


async def benchmark_skill_matching(iterations: int = 100) -> BenchmarkResult:
    """Benchmark skill matching for tasks."""
    skills = [
        {"name": "code_generation", "keywords": ["write", "create", "implement"]},
        {"name": "debugging", "keywords": ["debug", "fix", "error"]},
        {"name": "analysis", "keywords": ["analyze", "research", "study"]},
    ]

    goals = [t["goal"] for t in SAMPLE_TASKS]

    async def match_skill():
        import random
        goal = random.choice(goals)
        goal_lower = goal.lower()

        matches = []
        for skill in skills:
            for kw in skill["keywords"]:
                if kw in goal_lower:
                    matches.append(skill["name"])
                    break

        return matches or ["default"]

    return await benchmark_async("Skill Matching", match_skill, iterations)


def run_all_benchmarks() -> List[BenchmarkResult]:
    """Run all benchmarks and return results."""
    results = []

    print("Running performance benchmarks...")
    print("=" * 60)

    # Synchronous benchmarks
    print("\nSynchronous Benchmarks:")
    print("-" * 40)

    result = benchmark_routing_simulation(100)
    results.append(result)
    print(f"Task Routing: {result.avg_time * 1000:.3f}ms avg ({result.ops_per_second:.1f} ops/s)")

    result = benchmark_task_serialization(1000)
    results.append(result)
    print(f"Task Serialization: {result.avg_time * 1000:.3f}ms avg ({result.ops_per_second:.1f} ops/s)")

    result = benchmark_scheduler_scoring(200)
    results.append(result)
    print(f"Scheduler Scoring: {result.avg_time * 1000:.3f}ms avg ({result.ops_per_second:.1f} ops/s)")

    # Async benchmarks
    print("\nAsynchronous Benchmarks:")
    print("-" * 40)

    result = asyncio.run(benchmark_agent_dispatch_simulation(50))
    results.append(result)
    print(f"Agent Dispatch (simulated): {result.avg_time * 1000:.3f}ms avg ({result.ops_per_second:.1f} ops/s)")

    result = asyncio.run(benchmark_event_bus_publish(1000))
    results.append(result)
    print(f"Event Bus Publish: {result.avg_time * 1000:.3f}ms avg ({result.ops_per_second:.1f} ops/s)")

    result = asyncio.run(benchmark_skill_matching(100))
    results.append(result)
    print(f"Skill Matching: {result.avg_time * 1000:.3f}ms avg ({result.ops_per_second:.1f} ops/s)")

    print("\n" + "=" * 60)
    print("Benchmark Summary:")
    print("-" * 40)
    for r in results:
        print(f"{r.name:30} {r.avg_time * 1000:8.3f}ms  (std: {r.std_dev * 1000:.3f}ms)")

    return results


if __name__ == "__main__":
    run_all_benchmarks()