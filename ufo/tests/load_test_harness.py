"""
UFO Framework High-Concurrency Load Testing Harness.

Spawns and orchestrates 50+ to 100s of simultaneous agent requests against the
UFO Galaxy and Simplified task constellation frameworks.

Features:
- Bounded concurrency using asyncio.Semaphore(max_concurrency)
- Real-time telemetry tracking: RPS, TPS, latency percentiles (p50, p90, p95, p99), success/error counts
- Zero framework crash assertions and stability threshold verification
- Executable via CLI with configurable profiles and modes.
"""
import argparse
import asyncio
import json
import logging
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tests_dir = os.path.dirname(os.path.abspath(__file__))
if tests_dir in sys.path:
    sys.path.remove(tests_dir)
if project_root in sys.path:
    sys.path.remove(project_root)
sys.path.insert(0, project_root)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
logging.getLogger('ufo').setLevel(logging.ERROR)
logging.getLogger('galaxy').setLevel(logging.ERROR)
from ufo.galaxy.constellation import TaskConstellationOrchestrator, TaskConstellation, TaskStar, TaskStarLine, TaskStatus, TaskPriority, ConstellationState, DeviceType
from ufo.galaxy.core.types import ExecutionResult
from ufo.galaxy.core.events import EventBus

@dataclass
class RequestResult:
    """Telemetry data captured for a single load test request."""
    request_id: int
    mode: str
    dag_type: str
    success: bool
    wall_time_sec: float
    task_count: int
    completed_tasks: int
    error_message: Optional[str] = None
    start_timestamp: float = 0.0
    end_timestamp: float = 0.0

class IsolatedMockDeviceManager:
    """Thread-safe, non-blocking mock device manager for load test workers."""

    def __init__(self, mock_latency: float=0.001):
        self.mock_latency = mock_latency
        self._connected_devices = {'web_device_01': {'device_type': 'web', 'status': 'connected'}, 'office_device_01': {'device_type': 'office', 'status': 'connected'}, 'mobile_device_01': {'device_type': 'mobile', 'status': 'connected'}, 'desktop_device_01': {'device_type': 'desktop', 'status': 'connected'}, 'cloud_service_01': {'device_type': 'cloud', 'status': 'connected'}}
        self.connected_devices = self._connected_devices

    def get_all_devices(self) -> Dict[str, Any]:
        return self._connected_devices

    def get_connected_devices(self) -> List[str]:
        return list(self._connected_devices.keys())

    async def assign_task_to_device(self, task_id: str, device_id: str, target_client_id: Optional[str]=None, task_description: str='', task_data: Optional[Dict[str, Any]]=None, timeout: float=300.0) -> ExecutionResult:
        if self.mock_latency > 0:
            await asyncio.sleep(self.mock_latency)
        return ExecutionResult(task_id=task_id, status='completed', result={'message': f"Successfully executed '{task_description}' on {device_id}"}, metadata={'device_id': device_id, 'execution_time': self.mock_latency})

class LoadMetricsCollector:
    """Aggregates real-time performance telemetry and computes statistical percentiles."""

    def __init__(self):
        self.results: List[RequestResult] = []
        self._lock = asyncio.Lock()
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.framework_crashes: int = 0

    async def record_result(self, result: RequestResult):
        async with self._lock:
            self.results.append(result)
            if not result.success and 'crash' in (result.error_message or '').lower():
                self.framework_crashes += 1

    @staticmethod
    def _percentile(sorted_data: List[float], p: float) -> float:
        if not sorted_data:
            return 0.0
        k = (len(sorted_data) - 1) * (p / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        d0 = sorted_data[int(f)] * (c - k)
        d1 = sorted_data[int(c)] * (k - f)
        return d0 + d1

    def compute_summary(self) -> Dict[str, Any]:
        total_requests = len(self.results)
        if total_requests == 0:
            return {'error': 'No requests recorded'}
        successful = [r for r in self.results if r.success]
        failed = [r for r in self.results if not r.success]
        total_duration = max(0.001, self.end_time - self.start_time)
        latencies = sorted([r.wall_time_sec for r in self.results])
        total_tasks = sum((r.task_count for r in self.results))
        completed_tasks = sum((r.completed_tasks for r in self.results))
        success_count = len(successful)
        failed_count = len(failed)
        success_rate = success_count / total_requests * 100.0
        rps = total_requests / total_duration
        tps = completed_tasks / total_duration
        p50 = self._percentile(latencies, 50)
        p90 = self._percentile(latencies, 90)
        p95 = self._percentile(latencies, 95)
        p99 = self._percentile(latencies, 99)
        min_lat = latencies[0] if latencies else 0.0
        max_lat = latencies[-1] if latencies else 0.0
        mean_lat = sum(latencies) / total_requests if total_requests else 0.0
        errors_summary = [r.error_message for r in failed if r.error_message]
        return {'timestamp': datetime.now().isoformat(), 'total_requests': total_requests, 'success_count': success_count, 'error_count': failed_count, 'framework_crashes': self.framework_crashes, 'success_rate_pct': round(success_rate, 2), 'total_tasks': total_tasks, 'completed_tasks': completed_tasks, 'total_duration_sec': round(total_duration, 4), 'rps': round(rps, 2), 'tps': round(tps, 2), 'latencies_sec': {'min': round(min_lat, 4), 'p50': round(p50, 4), 'p90': round(p90, 4), 'p95': round(p95, 4), 'p99': round(p99, 4), 'max': round(max_lat, 4), 'mean': round(mean_lat, 4)}, 'error_messages': errors_summary[:10]}

class UFOLoadTestRunner:
    """
    Main Load Testing Engine for Microsoft UFO.
    Uses asyncio.Semaphore for concurrency throttling across hundreds of agent requests.
    """

    def __init__(self, concurrency: int=50, total_requests: int=100, mode: str='galaxy', profile: str='burst', duration: float=0.0, output_json: Optional[str]=None, mock_latency: float=0.001):
        self.concurrency = concurrency
        self.total_requests = total_requests
        self.mode = mode.lower()
        self.profile = profile.lower()
        self.duration = duration
        self.output_json = output_json
        self.mock_latency = mock_latency
        self.collector = LoadMetricsCollector()

    def _create_synthetic_constellation(self, req_id: int, dag_type: str) -> TaskConstellation:
        """Construct synthetic TaskConstellation instances for different graph topologies."""
        constellation = TaskConstellation(name=f'LoadTest_Req_{req_id}_{dag_type}')
        if dag_type == 'linear':
            tasks = [TaskStar(f't_{req_id}_1', description='Init task', priority=TaskPriority.HIGH, target_device_id='desktop_device_01'), TaskStar(f't_{req_id}_2', description='Process data', priority=TaskPriority.MEDIUM, target_device_id='office_device_01'), TaskStar(f't_{req_id}_3', description='Validate output', priority=TaskPriority.HIGH, target_device_id='cloud_service_01')]
            for t in tasks:
                constellation.add_task(t)
            constellation.add_dependency(TaskStarLine.create_success_only(f't_{req_id}_1', f't_{req_id}_2'))
            constellation.add_dependency(TaskStarLine.create_success_only(f't_{req_id}_2', f't_{req_id}_3'))
        elif dag_type == 'parallel':
            start_task = TaskStar(f't_{req_id}_start', description='Start fan-out', priority=TaskPriority.HIGH, target_device_id='desktop_device_01')
            constellation.add_task(start_task)
            end_task = TaskStar(f't_{req_id}_end', description='Aggregate results', priority=TaskPriority.HIGH, target_device_id='cloud_service_01')
            constellation.add_task(end_task)
            for i in range(5):
                p_task = TaskStar(f't_{req_id}_p{i}', description=f'Parallel worker {i}', priority=TaskPriority.MEDIUM, target_device_id='web_device_01')
                constellation.add_task(p_task)
                constellation.add_dependency(TaskStarLine.create_success_only(start_task.task_id, p_task.task_id))
                constellation.add_dependency(TaskStarLine.create_success_only(p_task.task_id, end_task.task_id))
        elif dag_type == 'diamond':
            start_task = TaskStar(f't_{req_id}_start', description='Start diamond', priority=TaskPriority.HIGH, target_device_id='desktop_device_01')
            left_task = TaskStar(f't_{req_id}_left', description='Branch Left', priority=TaskPriority.MEDIUM, target_device_id='web_device_01')
            right_task = TaskStar(f't_{req_id}_right', description='Branch Right', priority=TaskPriority.MEDIUM, target_device_id='office_device_01')
            join_task = TaskStar(f't_{req_id}_join', description='Join Branches', priority=TaskPriority.HIGH, target_device_id='cloud_service_01')
            for t in [start_task, left_task, right_task, join_task]:
                constellation.add_task(t)
            constellation.add_dependency(TaskStarLine.create_success_only(start_task.task_id, left_task.task_id))
            constellation.add_dependency(TaskStarLine.create_success_only(start_task.task_id, right_task.task_id))
            constellation.add_dependency(TaskStarLine.create_success_only(left_task.task_id, join_task.task_id))
            constellation.add_dependency(TaskStarLine.create_success_only(right_task.task_id, join_task.task_id))
        else:
            tasks = [TaskStar(f't_{req_id}_kickoff', description='Kickoff project', priority=TaskPriority.HIGH, target_device_id='desktop_device_01'), TaskStar(f't_{req_id}_res', description='Research phase', priority=TaskPriority.MEDIUM, target_device_id='web_device_01'), TaskStar(f't_{req_id}_arch', description='Design architecture', priority=TaskPriority.HIGH, target_device_id='office_device_01'), TaskStar(f't_{req_id}_dev1', description='Develop module 1', priority=TaskPriority.MEDIUM, target_device_id='desktop_device_01'), TaskStar(f't_{req_id}_dev2', description='Develop module 2', priority=TaskPriority.MEDIUM, target_device_id='desktop_device_01'), TaskStar(f't_{req_id}_test', description='Integration test', priority=TaskPriority.HIGH, target_device_id='cloud_service_01')]
            for t in tasks:
                constellation.add_task(t)
            constellation.add_dependency(TaskStarLine.create_success_only(f't_{req_id}_kickoff', f't_{req_id}_res'))
            constellation.add_dependency(TaskStarLine.create_success_only(f't_{req_id}_res', f't_{req_id}_arch'))
            constellation.add_dependency(TaskStarLine.create_success_only(f't_{req_id}_arch', f't_{req_id}_dev1'))
            constellation.add_dependency(TaskStarLine.create_success_only(f't_{req_id}_arch', f't_{req_id}_dev2'))
            constellation.add_dependency(TaskStarLine.create_success_only(f't_{req_id}_dev1', f't_{req_id}_test'))
            constellation.add_dependency(TaskStarLine.create_success_only(f't_{req_id}_dev2', f't_{req_id}_test'))
        return constellation

    async def _execute_simplified_request(self, req_id: int, dag_type: str) -> Tuple[bool, int, int, Optional[str]]:
        """Execute request using Simplified state machine direct completion."""
        try:
            constellation = self._create_synthetic_constellation(req_id, dag_type)
            task_count = constellation.task_count
            constellation.start_execution()
            topo_order = constellation.get_topological_order()
            for task_id in topo_order:
                if self.mock_latency > 0:
                    await asyncio.sleep(self.mock_latency)
                constellation.mark_task_completed(task_id, success=True)
            completed = len(constellation.get_completed_tasks())
            return (True, task_count, completed, None)
        except Exception as e:
            return (False, 0, 0, f'Simplified execution failure: {str(e)}')

    async def _execute_galaxy_request(self, req_id: int, dag_type: str) -> Tuple[bool, int, int, Optional[str]]:
        """Execute request using full Galaxy TaskConstellationOrchestrator pipeline."""
        try:
            device_manager = IsolatedMockDeviceManager(mock_latency=self.mock_latency)
            event_bus = EventBus()
            orchestrator = TaskConstellationOrchestrator(device_manager=device_manager, enable_logging=False, event_bus=event_bus)
            constellation = self._create_synthetic_constellation(req_id, dag_type)
            task_count = constellation.task_count
            res = await orchestrator.orchestrate_constellation(constellation)
            completed = len(constellation.get_completed_tasks())
            success = res.get('status') == 'completed'
            return (success, task_count, completed, None)
        except Exception as e:
            return (False, 0, 0, f'Galaxy orchestration failure: {str(e)}')

    async def run_single_request(self, req_id: int, semaphore: asyncio.Semaphore) -> RequestResult:
        """Run a single request guarded by the asyncio.Semaphore."""
        async with semaphore:
            dag_types = ['linear', 'parallel', 'diamond', 'complex']
            dag_type = dag_types[req_id % len(dag_types)]
            active_mode = self.mode
            if self.mode == 'all':
                active_mode = 'galaxy' if req_id % 2 == 0 else 'simplified'
            start_t = time.perf_counter()
            start_ts = time.time()
            if active_mode == 'galaxy':
                success, total_t, comp_t, err = await self._execute_galaxy_request(req_id, dag_type)
            else:
                success, total_t, comp_t, err = await self._execute_simplified_request(req_id, dag_type)
            end_t = time.perf_counter()
            end_ts = time.time()
            wall_time = end_t - start_t
            res = RequestResult(request_id=req_id, mode=active_mode, dag_type=dag_type, success=success, wall_time_sec=wall_time, task_count=total_t, completed_tasks=comp_t, error_message=err, start_timestamp=start_ts, end_timestamp=end_ts)
            await self.collector.record_result(res)
            return res

    async def run(self) -> Dict[str, Any]:
        """Execute the load test suite with specified concurrency and profile."""
        print(f'🚀 Starting UFO Load Test Harness')
        print(f'   - Target Concurrency: {self.concurrency}')
        print(f'   - Total Requests: {self.total_requests}')
        print(f'   - Orchestration Mode: {self.mode.upper()}')
        print(f'   - Load Profile: {self.profile.upper()}')
        print('=' * 60)
        sem = asyncio.Semaphore(self.concurrency)
        self.collector.start_time = time.time()
        if self.profile == 'ramp':
            tasks = []
            stagger = (self.duration if self.duration > 0 else 2.0) / self.total_requests
            for i in range(self.total_requests):
                await asyncio.sleep(stagger)
                tasks.append(asyncio.create_task(self.run_single_request(i, sem)))
            await asyncio.gather(*tasks)
        else:
            tasks = [self.run_single_request(i, sem) for i in range(self.total_requests)]
            await asyncio.gather(*tasks)
        self.collector.end_time = time.time()
        summary = self.collector.compute_summary()
        print('\n📊 Load Test Benchmarking Results Summary')
        print('=' * 60)
        print(f'   - Concurrency Limit     : {self.concurrency}')
        print(f"   - Total Requests        : {summary['total_requests']}")
        print(f"   - Successful Requests   : {summary['success_count']}")
        print(f"   - Failed Requests       : {summary['error_count']}")
        print(f"   - Framework Crashes     : {summary['framework_crashes']}")
        print(f"   - Success Rate          : {summary['success_rate_pct']}%")
        print(f"   - Total Execution Time  : {summary['total_duration_sec']} sec")
        print(f"   - Throughput (RPS)      : {summary['rps']} req/sec")
        print(f"   - Task Throughput (TPS) : {summary['tps']} tasks/sec")
        print(f"   - Latency p50 (Median)  : {summary['latencies_sec']['p50']}s")
        print(f"   - Latency p90           : {summary['latencies_sec']['p90']}s")
        print(f"   - Latency p95           : {summary['latencies_sec']['p95']}s")
        print(f"   - Latency p99           : {summary['latencies_sec']['p99']}s")
        print(f"   - Latency Min / Max     : {summary['latencies_sec']['min']}s / {summary['latencies_sec']['max']}s")
        print('=' * 60)
        if self.output_json:
            output_dir = os.path.dirname(self.output_json)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            with open(self.output_json, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2)
            print(f'💾 Report saved to: {self.output_json}')
        assert summary['framework_crashes'] == 0, f"Framework crashed {summary['framework_crashes']} times!"
        assert summary['error_count'] == 0, f"{summary['error_count']} requests failed!"
        assert summary['success_rate_pct'] == 100.0, f"Success rate dropped to {summary['success_rate_pct']}%!"
        print('✅ ALL FRAMEWORK STABILITY ASSERTIONS PASSED! ZERO CRASHES DETECTED.')
        return summary

def main():
    parser = argparse.ArgumentParser(description='UFO High-Concurrency Load Testing Harness')
    parser.add_argument('--concurrency', type=int, default=50, help='Maximum concurrent requests (default: 50)')
    parser.add_argument('--total-requests', type=int, default=100, help='Total requests to execute (default: 100)')
    parser.add_argument('--mode', type=str, default='galaxy', choices=['galaxy', 'simplified', 'all'], help='Orchestration framework mode')
    parser.add_argument('--profile', type=str, default='burst', choices=['burst', 'ramp', 'sustained'], help='Load generator traffic profile')
    parser.add_argument('--duration', type=float, default=0.0, help='Ramp duration in seconds')
    parser.add_argument('--output-json', type=str, default='logs/test_results/load_test_results.json', help='Path to save output JSON report')
    parser.add_argument('--mock-latency', type=float, default=0.001, help='Simulated mock device task latency in seconds')
    args = parser.parse_args()
    runner = UFOLoadTestRunner(concurrency=args.concurrency, total_requests=args.total_requests, mode=args.mode, profile=args.profile, duration=args.duration, output_json=args.output_json, mock_latency=args.mock_latency)
    try:
        asyncio.run(runner.run())
        sys.exit(0)
    except AssertionError as ae:
        print(f'\n❌ BENCHMARK ASSERTION FAILED: {ae}', file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f'\n💥 UNHANDLED LOAD TESTER ERROR: {e}', file=sys.stderr)
        sys.exit(1)
if __name__ == '__main__':
    main()