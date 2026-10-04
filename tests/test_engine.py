"""
Unit test suite for swarm-lite orchestration engine, memory bus, and lifecycle policies.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

from swarm_lite.bus import SwarmBus
from swarm_lite.cli import build_parser, main
from swarm_lite.engine import (
    LifecyclePolicy,
    LifecycleReasoningEngine,
    SwarmOrchestrator,
    TokenGovernor,
    Worker,
    WorkerStatus,
)


class TestSwarmBus(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.bus = SwarmBus(db_path=self.temp_db.name)

    def tearDown(self):
        self.bus.close()
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)

    def test_publish_and_get(self):
        row_id = self.bus.publish("key1", "value1", channel="test_chan", worker_id="w-01")
        self.assertGreater(row_id, 0)
        
        val = self.bus.get("key1", channel="test_chan")
        self.assertEqual(val, "value1")

    def test_get_nonexistent(self):
        val = self.bus.get("missing_key")
        self.assertIsNone(val)

    def test_query(self):
        self.bus.publish("k1", "v1", channel="chan1", worker_id="w-01")
        self.bus.publish("k2", "v2", channel="chan1", worker_id="w-02")
        self.bus.publish("k3", "v3", channel="chan2", worker_id="w-01")

        results = self.bus.query(channel="chan1")
        self.assertEqual(len(results), 2)

        worker_results = self.bus.query(worker_id="w-01")
        self.assertEqual(len(worker_results), 2)

    def test_clear(self):
        self.bus.publish("k1", "v1", channel="chan1")
        self.bus.publish("k2", "v2", channel="chan2")
        
        cleared_chan1 = self.bus.clear(channel="chan1")
        self.assertEqual(cleared_chan1, 1)
        self.assertIsNone(self.bus.get("k1", channel="chan1"))
        self.assertEqual(self.bus.get("k2", channel="chan2"), "v2")

        cleared_all = self.bus.clear()
        self.assertEqual(cleared_all, 1)
        self.assertIsNone(self.bus.get("k2", channel="chan2"))


class TestTokenGovernor(unittest.TestCase):
    def test_quota_within_limit(self):
        governor = TokenGovernor(default_max_tokens=1500)
        worker = Worker("w-1", max_tokens=1500)
        allowed, msg = governor.consume(worker, 500)
        self.assertTrue(allowed)
        self.assertEqual(worker.tokens_used, 500)
        self.assertEqual(worker.status, WorkerStatus.IDLE)

    def test_quota_exceeded(self):
        governor = TokenGovernor(default_max_tokens=1500)
        worker = Worker("w-1", max_tokens=1500)
        allowed, msg = governor.consume(worker, 1600)
        self.assertFalse(allowed)
        self.assertEqual(worker.tokens_used, 1600)
        self.assertEqual(worker.status, WorkerStatus.TERMINATED_QUOTA)


class TestLifecyclePolicies(unittest.TestCase):
    def setUp(self):
        self.engine = LifecycleReasoningEngine()

    def test_single_turn_immediate(self):
        worker = Worker("w-1", policy=LifecyclePolicy.SINGLE_TURN_IMMEDIATE)
        worker.current_turn = 1
        output = {"output": "Done linting", "verified": True, "diff_produced": True}
        terminate, reason, status = self.engine.evaluate(worker, output)
        self.assertTrue(terminate)
        self.assertEqual(status, WorkerStatus.COMPLETED)
        self.assertIn("single_turn_immediate", reason)

    def test_empirical_verification_bounded_success(self):
        worker = Worker("w-2", policy=LifecyclePolicy.EMPIRICAL_VERIFICATION_BOUNDED, max_turns=3)
        worker.current_turn = 1
        output = {"output": "Fixed bug", "verified": True}
        terminate, reason, status = self.engine.evaluate(worker, output)
        self.assertTrue(terminate)
        self.assertEqual(status, WorkerStatus.COMPLETED)

    def test_empirical_verification_bounded_continue(self):
        worker = Worker("w-2", policy=LifecyclePolicy.EMPIRICAL_VERIFICATION_BOUNDED, max_turns=3)
        worker.current_turn = 1
        output = {"output": "Attempted fix", "verified": False}
        terminate, reason, status = self.engine.evaluate(worker, output)
        self.assertFalse(terminate)
        self.assertEqual(status, WorkerStatus.RUNNING)

    def test_empirical_verification_bounded_max_turns(self):
        worker = Worker("w-2", policy=LifecyclePolicy.EMPIRICAL_VERIFICATION_BOUNDED, max_turns=3)
        worker.current_turn = 3
        output = {"output": "Attempted fix turn 3", "verified": False}
        terminate, reason, status = self.engine.evaluate(worker, output)
        self.assertTrue(terminate)
        self.assertEqual(status, WorkerStatus.TERMINATED_MAX_TURNS)

    def test_human_interactive_handoff(self):
        worker = Worker("w-3", policy=LifecyclePolicy.HUMAN_INTERACTIVE_HANDOFF)
        output = {"output": "Architectural ambiguity detected"}
        terminate, reason, status = self.engine.evaluate(worker, output)
        self.assertTrue(terminate)
        self.assertEqual(status, WorkerStatus.YIELDED_TO_HUMAN)

    def test_decay_guarded_stop(self):
        worker = Worker("w-4", policy=LifecyclePolicy.DECAY_GUARDED_STOP, max_turns=5)
        worker.current_turn = 1
        
        # Turn 1: No diff
        out1 = {"output": "No change", "diff_produced": False, "verified": False}
        terminate, reason, status = self.engine.evaluate(worker, out1)
        self.assertFalse(terminate)

        # Turn 2: No diff (consecutive = 2) -> Should terminate
        worker.current_turn = 2
        out2 = {"output": "Still no change", "diff_produced": False, "verified": False}
        terminate, reason, status = self.engine.evaluate(worker, out2)
        self.assertTrue(terminate)
        self.assertEqual(status, WorkerStatus.TERMINATED_DECAY)


class TestSwarmOrchestrator(unittest.TestCase):
    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp_db.close()
        self.orchestrator = SwarmOrchestrator(db_path=self.temp_db.name)

    def tearDown(self):
        self.orchestrator.close()
        if os.path.exists(self.temp_db.name):
            os.remove(self.temp_db.name)


    def test_register_and_step(self):
        worker = self.orchestrator.register_worker("w-alpha", task="Refactor module")
        self.assertEqual(worker.worker_id, "w-alpha")
        self.assertIn("w-alpha", self.orchestrator.workers)

        step_res = self.orchestrator.step_worker("w-alpha")
        self.assertTrue(step_res["terminated"])
        self.assertEqual(step_res["status"], WorkerStatus.COMPLETED.value)

    def test_fan_out_30_plus_workers(self):
        num_workers = 35
        specs = [
            {
                "worker_id": f"micro-agent-{i+1:02d}",
                "role": "worker",
                "task": f"Process chunk {i+1}",
                "policy": LifecyclePolicy.SINGLE_TURN_IMMEDIATE.value,
                "max_tokens": 1500,
            }
            for i in range(num_workers)
        ]
        
        res = self.orchestrator.fan_out(specs)
        self.assertEqual(res["total_workers"], 35)
        self.assertEqual(len(self.orchestrator.workers), 35)
        
        status_summary = self.orchestrator.get_status()
        self.assertEqual(status_summary["status_counts"].get("completed", 0), 35)

    def test_render_matrix(self):
        self.orchestrator.register_worker("w-01", role="linter", policy=LifecyclePolicy.SINGLE_TURN_IMMEDIATE)
        self.orchestrator.register_worker("w-02", role="tester", policy=LifecyclePolicy.EMPIRICAL_VERIFICATION_BOUNDED)
        matrix = self.orchestrator.render_matrix()
        self.assertIn("MODUS SWARM LITE MATRIX", matrix)
        self.assertIn("w-01", matrix)
        self.assertIn("w-02", matrix)
        self.orchestrator.close()



class TestCLI(unittest.TestCase):
    def test_cli_parser(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--workers", "10", "--policy", "decay_guarded_stop"])
        self.assertEqual(args.command, "run")
        self.assertEqual(args.workers, 10)
        self.assertEqual(args.policy, "decay_guarded_stop")

    def test_cli_main_status(self):
        ret = main(["status"])
        self.assertEqual(ret, 0)

    def test_cli_main_render(self):
        ret = main(["render"])
        self.assertEqual(ret, 0)


if __name__ == "__main__":
    unittest.main()
