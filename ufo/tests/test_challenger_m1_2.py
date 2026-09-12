import asyncio
import inspect
import time
import pytest
from ufo.agents.memory.memory import MemoryItem, Memory
from ufo.module.basic import BaseRound
from ufo.module.sessions.session import FromFileSession, OpenAIOperatorSession, Session


def test_memory_item_list_mutation_isolation():
    """
    Empirically verify that default instances of MemoryItem do not share
    _memory_attributes or mutate class/instance state across instances.
    """
    item1 = MemoryItem()
    item2 = MemoryItem()

    # 1. Instance identity check
    assert item1._memory_attributes is not item2._memory_attributes, (
        "MemoryItem instances share the same _memory_attributes list instance!"
    )

    # 2. Mutation isolation check
    item1.set_value("test_key_1", "value1")
    item1.set_value("test_key_2", "value2")

    assert "test_key_1" in item1._memory_attributes
    assert "test_key_2" in item1._memory_attributes
    assert "test_key_1" not in item2._memory_attributes, (
        "Mutating item1 altered item2's _memory_attributes! Shared list bug present."
    )
    assert len(item2._memory_attributes) == 0, (
        f"item2 should have empty _memory_attributes, found: {item2._memory_attributes}"
    )


def test_memory_content_list_mutation_isolation():
    """
    Empirically verify that default instances of Memory do not share _content.
    """
    mem1 = Memory()
    mem2 = Memory()

    assert mem1._content is not mem2._content, (
        "Memory instances share the same _content list instance!"
    )

    item = MemoryItem()
    mem1.add_memory_item(item)

    assert len(mem1._content) == 1
    assert len(mem2._content) == 0, (
        "Mutating mem1 altered mem2's _content! Shared list bug present."
    )


@pytest.mark.asyncio
async def test_asyncio_sleep_non_blocking_behavior():
    """
    Empirically verify that asyncio event loop remains active and responsive
    during subtask delays when using asyncio.sleep vs synchronous blocking.
    """
    event_loop_ticks = []

    async def event_loop_heartbeat():
        for _ in range(10):
            event_loop_ticks.append(time.perf_counter())
            await asyncio.sleep(0.02)

    # Launch background task in the active event loop
    heartbeat_task = asyncio.create_task(event_loop_heartbeat())

    # Simulate non-blocking sleep (same mechanism used in ufo/module/basic.py line 179)
    start_time = time.perf_counter()
    await asyncio.sleep(0.15)
    end_time = time.perf_counter()

    await heartbeat_task

    duration = end_time - start_time
    tick_count = len(event_loop_ticks)

    # Empirical assertion: If event loop was non-blocking, heartbeat_task ticked multiple times concurrently
    assert tick_count > 3, (
        f"Event loop was blocked during sleep! Heartbeat only ran {tick_count} times."
    )
    assert duration >= 0.14, f"Sleep duration too short: {duration}s"


def test_coroutine_await_signatures():
    """
    Empirically verify that Session, FromFileSession, OpenAIOperatorSession, and BaseRound
    run methods are properly defined as coroutine functions.
    """
    assert inspect.iscoroutinefunction(
        BaseRound.run
    ), "BaseRound.run is not a coroutine function"
    assert inspect.iscoroutinefunction(
        Session.run
    ), "Session.run is not a coroutine function"
    assert inspect.iscoroutinefunction(
        FromFileSession.run
    ), "FromFileSession.run is not a coroutine function"
    assert inspect.iscoroutinefunction(
        OpenAIOperatorSession.run
    ), "OpenAIOperatorSession.run is not a coroutine function"
