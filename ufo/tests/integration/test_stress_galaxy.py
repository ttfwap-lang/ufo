#!/usr/bin/env python3
import asyncio
import os
import sys
import logging
import time

project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from ufo.galaxy.constellation import TaskConstellationOrchestrator, TaskConstellation, TaskStar, TaskPriority
from tests.integration.test_e2e_galaxy import MockGalaxyConstellationClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

async def run_stress_test(num_constellations=50):
    logger.info(f"Starting UFO Action Stress Test with {num_constellations} concurrent constellations!")
    
    client = MockGalaxyConstellationClient()
    client.device_manager.get_all_devices = lambda: client.connected_devices
    client.device_manager._connected_devices = client.connected_devices
    device_manager = client.device_manager
    
    orchestrator = TaskConstellationOrchestrator(device_manager=device_manager)
    
    constellations = []
    for i in range(num_constellations):
        c = TaskConstellation(name=f"StressConstellation_{i}")
        task1 = TaskStar(task_id=f"task_{i}_1", name=f"Task1_{i}", description="Stress Task 1", priority=TaskPriority.HIGH)
        task2 = TaskStar(task_id=f"task_{i}_2", name=f"Task2_{i}", description="Stress Task 2", priority=TaskPriority.MEDIUM)
        task3 = TaskStar(task_id=f"task_{i}_3", name=f"Task3_{i}", description="Stress Task 3", priority=TaskPriority.LOW)
        
        c.add_task(task1)
        c.add_task(task2)
        c.add_task(task3)
        
        c.add_dependency(task1.task_id, task2.task_id)
        c.add_dependency(task2.task_id, task3.task_id)
        
        constellations.append(c)

    start_time = time.time()
    
    # Execute all constellations CONCURRENTLY
    tasks = [orchestrator.orchestrate_constellation(c, assignment_strategy="round_robin") for c in constellations]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    end_time = time.time()
    
    success_count = 0
    fail_count = 0
    
    for i, res in enumerate(results):
        if isinstance(res, Exception):
            fail_count += 1
            logger.error(f"Constellation {i} failed: {res}")
        else:
            success_count += 1

    logger.info("="*50)
    logger.info("UFO STRESS TEST RESULTS")
    logger.info("="*50)
    logger.info(f"Total Time: {end_time - start_time:.2f} seconds")
    logger.info(f"Success: {success_count} / {num_constellations}")
    logger.info(f"Failed: {fail_count} / {num_constellations}")
    logger.info(f"Throughput: {(num_constellations * 3) / (end_time - start_time):.2f} tasks/sec")
    logger.info("="*50)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_stress_test(50))
