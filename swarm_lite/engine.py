"""
Micro-worker swarm orchestrator engine with dynamic adaptive lifecycle control
and ultra-low token quota governance (<= 1500 tokens/worker).
"""

import time
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from swarm_lite.bus import SwarmBus


class LifecyclePolicy(str, Enum):
    """Adaptive worker lifecycle policies for ultra-low token consumption."""
    SINGLE_TURN_IMMEDIATE = "single_turn_immediate"
    EMPIRICAL_VERIFICATION_BOUNDED = "empirical_verification_bounded"
    HUMAN_INTERACTIVE_HANDOFF = "human_interactive_handoff"
    DECAY_GUARDED_STOP = "decay_guarded_stop"


class WorkerStatus(str, Enum):
    """Lifecycle statuses for swarm micro-workers."""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    YIELDED_TO_HUMAN = "yielded_to_human"
    TERMINATED_QUOTA = "terminated_quota"
    TERMINATED_DECAY = "terminated_decay"
    TERMINATED_MAX_TURNS = "terminated_max_turns"


class Worker:
    """Represents a micro-worker agent in the swarm."""

    def __init__(
        self,
        worker_id: str,
        role: str = "worker",
        task: str = "",
        policy: Union[LifecyclePolicy, str] = LifecyclePolicy.SINGLE_TURN_IMMEDIATE,
        max_tokens: int = 1500,
        max_turns: int = 3,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.worker_id = worker_id
        self.role = role
        self.task = task
        self.policy = LifecyclePolicy(policy)
        self.max_tokens = max_tokens
        self.max_turns = max_turns
        self.current_turn = 0
        self.tokens_used = 0
        self.status = WorkerStatus.IDLE
        self.consecutive_no_progress = 0
        self.created_at = time.time()
        self.updated_at = time.time()
        self.metadata = metadata or {}
        self.history: List[Dict[str, Any]] = []
        self.result: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert worker state to dictionary."""
        return {
            "worker_id": self.worker_id,
            "role": self.role,
            "task": self.task,
            "policy": self.policy.value,
            "max_tokens": self.max_tokens,
            "max_turns": self.max_turns,
            "current_turn": self.current_turn,
            "tokens_used": self.tokens_used,
            "status": self.status.value,
            "consecutive_no_progress": self.consecutive_no_progress,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "result": self.result,
        }


class TokenGovernor:
    """
    Token quota governor ensuring micro-worker token allocations adhere
    strictly to the low-token threshold (default <= 1500 tokens/worker).
    """

    def __init__(self, default_max_tokens: int = 1500):
        self.default_max_tokens = default_max_tokens

    def consume(self, worker: Worker, token_count: int) -> Tuple[bool, str]:
        """
        Record token consumption for a worker and check against quota.
        Returns (is_allowed, reason).
        """
        if worker.tokens_used + token_count > worker.max_tokens:
            worker.tokens_used += token_count
            worker.status = WorkerStatus.TERMINATED_QUOTA
            worker.updated_at = time.time()
            return False, f"Token quota exceeded ({worker.tokens_used}/{worker.max_tokens})"
        
        worker.tokens_used += token_count
        worker.updated_at = time.time()
        return True, "Token quota OK"


class LifecycleReasoningEngine:
    """
    Dynamic adaptive reasoning engine evaluating auto-termination lifecycle policies.
    """

    def evaluate(self, worker: Worker, turn_output: Dict[str, Any]) -> Tuple[bool, str, WorkerStatus]:
        """
        Evaluates worker continuation or termination based on policy and turn output.
        
        Returns:
            (should_terminate: bool, reason: str, target_status: WorkerStatus)
        """
        policy = worker.policy
        verified = turn_output.get("verified", False)
        diff_produced = turn_output.get("diff_produced", False)
        output = turn_output.get("output", "")

        # 1. Single Turn Immediate
        if policy == LifecyclePolicy.SINGLE_TURN_IMMEDIATE:
            return True, "Auto-terminated post 1st turn output per single_turn_immediate policy", WorkerStatus.COMPLETED

        # 2. Empirical Verification Bounded
        if policy == LifecyclePolicy.EMPIRICAL_VERIFICATION_BOUNDED:
            if verified:
                return True, "Empirical verification test passed successfully", WorkerStatus.COMPLETED
            if worker.current_turn >= worker.max_turns:
                return True, f"Max turn bound ({worker.max_turns}) reached without empirical verification", WorkerStatus.TERMINATED_MAX_TURNS
            return False, "Pending empirical verification", WorkerStatus.RUNNING

        # 3. Human Interactive Handoff
        if policy == LifecyclePolicy.HUMAN_INTERACTIVE_HANDOFF:
            return True, "Yielded execution to human interactive handoff", WorkerStatus.YIELDED_TO_HUMAN

        # 4. Decay Guarded Stop
        if policy == LifecyclePolicy.DECAY_GUARDED_STOP:
            if diff_produced:
                worker.consecutive_no_progress = 0
            else:
                worker.consecutive_no_progress += 1

            if worker.consecutive_no_progress >= 2:
                return True, "Decay guarded stop: 2 consecutive turns without file diff or progress", WorkerStatus.TERMINATED_DECAY

            if worker.tokens_used >= worker.max_tokens:
                return True, f"Decay guarded stop: token budget cap ({worker.max_tokens}) reached", WorkerStatus.TERMINATED_QUOTA

            if verified:
                return True, "Decay guarded stop: goal accomplished", WorkerStatus.COMPLETED

            if worker.current_turn >= worker.max_turns:
                return True, f"Decay guarded stop: max turns ({worker.max_turns}) reached", WorkerStatus.TERMINATED_MAX_TURNS

            return False, "Progressing cleanly within decay boundaries", WorkerStatus.RUNNING

        return False, "Unknown policy evaluation", WorkerStatus.RUNNING


class SwarmOrchestrator:
    """
    High-throughput micro-worker swarm orchestrator capable of running 30+ workers
    under strict low-token limits and WAL-backed ephemeral state bus.
    """

    def __init__(
        self,
        db_path: Optional[Union[str, Path]] = None,
        default_max_tokens: int = 1500,
    ):
        self.bus = SwarmBus(db_path=db_path)
        self.governor = TokenGovernor(default_max_tokens=default_max_tokens)
        self.lifecycle_engine = LifecycleReasoningEngine()
        self.workers: Dict[str, Worker] = {}

    def register_worker(
        self,
        worker_id: str,
        role: str = "worker",
        task: str = "",
        policy: Union[LifecyclePolicy, str] = LifecyclePolicy.SINGLE_TURN_IMMEDIATE,
        max_tokens: int = 1500,
        max_turns: int = 3,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Worker:
        """Register a new micro-worker agent in the swarm orchestrator."""
        worker = Worker(
            worker_id=worker_id,
            role=role,
            task=task,
            policy=policy,
            max_tokens=max_tokens,
            max_turns=max_turns,
            metadata=metadata,
        )
        self.workers[worker_id] = worker
        self.bus.publish(
            key="registered",
            value=f"Worker {worker_id} registered with policy {worker.policy.value}",
            channel="lifecycle",
            worker_id=worker_id,
        )
        return worker

    def step_worker(
        self,
        worker_id: str,
        turn_func: Optional[Callable[[Worker], Dict[str, Any]]] = None,
        provided_output: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute one step/turn for a specified worker.
        """
        if worker_id not in self.workers:
            raise KeyError(f"Worker '{worker_id}' is not registered.")

        worker = self.workers[worker_id]
        if worker.status in (
            WorkerStatus.COMPLETED,
            WorkerStatus.FAILED,
            WorkerStatus.YIELDED_TO_HUMAN,
            WorkerStatus.TERMINATED_QUOTA,
            WorkerStatus.TERMINATED_DECAY,
            WorkerStatus.TERMINATED_MAX_TURNS,
        ):
            return {
                "worker_id": worker_id,
                "status": worker.status.value,
                "terminated": True,
                "reason": f"Worker already in terminal status: {worker.status.value}",
            }

        worker.status = WorkerStatus.RUNNING
        worker.current_turn += 1

        # Generate output via callback or provided output
        if turn_func:
            turn_output = turn_func(worker)
        elif provided_output:
            turn_output = provided_output
        else:
            turn_output = {
                "output": f"Turn {worker.current_turn} executed default payload",
                "tokens": 150,
                "verified": True,
                "diff_produced": True,
            }

        tokens_consumed = turn_output.get("tokens", 100)
        allowed, gov_reason = self.governor.consume(worker, tokens_consumed)

        if not allowed:
            self.bus.publish(
                key="quota_exceeded",
                value=gov_reason,
                channel="governance",
                worker_id=worker_id,
            )
            return {
                "worker_id": worker_id,
                "status": worker.status.value,
                "terminated": True,
                "reason": gov_reason,
            }

        # Evaluate lifecycle policy
        should_terminate, reason, target_status = self.lifecycle_engine.evaluate(worker, turn_output)

        worker.history.append({
            "turn": worker.current_turn,
            "output": turn_output.get("output", ""),
            "tokens": tokens_consumed,
            "reason": reason,
        })
        worker.result = turn_output.get("output", worker.result)

        if should_terminate:
            worker.status = target_status
            worker.updated_at = time.time()
            self.bus.publish(
                key="terminated",
                value=f"Status: {target_status.value} | Reason: {reason}",
                channel="lifecycle",
                worker_id=worker_id,
            )
            return {
                "worker_id": worker_id,
                "status": worker.status.value,
                "terminated": True,
                "reason": reason,
                "turn_output": turn_output,
            }

        worker.updated_at = time.time()
        self.bus.publish(
            key="turn_complete",
            value=f"Turn {worker.current_turn} complete | Tokens: {worker.tokens_used}/{worker.max_tokens}",
            channel="execution",
            worker_id=worker_id,
        )
        return {
            "worker_id": worker_id,
            "status": worker.status.value,
            "terminated": False,
            "reason": reason,
            "turn_output": turn_output,
        }

    def fan_out(
        self,
        worker_specs: List[Dict[str, Any]],
        runner_func: Optional[Callable[[Worker], Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Fan out execution across multiple micro-workers (supports 30+ workers).
        """
        registered = []
        for spec in worker_specs:
            w = self.register_worker(
                worker_id=spec["worker_id"],
                role=spec.get("role", "worker"),
                task=spec.get("task", ""),
                policy=spec.get("policy", LifecyclePolicy.SINGLE_TURN_IMMEDIATE),
                max_tokens=spec.get("max_tokens", 1500),
                max_turns=spec.get("max_turns", 3),
                metadata=spec.get("metadata"),
            )
            registered.append(w)

        results = {}
        for worker in registered:
            # Run worker steps until termination
            step_results = []
            while worker.status in (WorkerStatus.IDLE, WorkerStatus.RUNNING):
                res = self.step_worker(worker.worker_id, turn_func=runner_func)
                step_results.append(res)
                if res["terminated"]:
                    break
            results[worker.worker_id] = {
                "final_status": worker.status.value,
                "turns_taken": worker.current_turn,
                "tokens_used": worker.tokens_used,
                "step_results": step_results,
            }

        return {
            "total_workers": len(registered),
            "summary": self.get_status(),
            "results": results,
        }

    def get_status(self) -> Dict[str, Any]:
        """Return executive status summary of all workers in the swarm."""
        total_workers = len(self.workers)
        status_counts: Dict[str, int] = {}
        total_tokens = 0

        for w in self.workers.values():
            status_str = w.status.value
            status_counts[status_str] = status_counts.get(status_str, 0) + 1
            total_tokens += w.tokens_used

        return {
            "total_workers": total_workers,
            "total_tokens_used": total_tokens,
            "avg_tokens_per_worker": round(total_tokens / total_workers, 2) if total_workers > 0 else 0,
            "status_counts": status_counts,
            "workers": [w.to_dict() for w in self.workers.values()],
        }

    def render_matrix(self) -> str:
        """Render executive ASCII dashboard matrix of worker state and token governance."""
        lines = []
        lines.append("==========================================================================================")
        lines.append("                               MODUS SWARM LITE MATRIX                                   ")
        lines.append("==========================================================================================")
        lines.append(f"{'WORKER ID':<18} | {'ROLE':<12} | {'POLICY':<28} | {'TOKENS':<10} | {'STATUS':<15}")
        lines.append("------------------------------------------------------------------------------------------")

        if not self.workers:
            lines.append("                      [ No micro-workers registered in active roster ]            ")
        else:
            for w in self.workers.values():
                token_str = f"{w.tokens_used}/{w.max_tokens}"
                lines.append(
                    f"{w.worker_id:<18} | {w.role:<12} | {w.policy.value:<28} | {token_str:<10} | {w.status.value:<15}"
                )

        lines.append("==========================================================================================")
        status_summary = self.get_status()
        lines.append(
            f"SUMMARY: Total Workers: {status_summary['total_workers']} | Total Tokens: {status_summary['total_tokens_used']} | Avg Tokens/Worker: {status_summary['avg_tokens_per_worker']}"
        )
        lines.append("==========================================================================================")
        return "\n".join(lines)

    def close(self) -> None:
        """Close the underlying SQLite state bus connection."""
        if hasattr(self, "bus") and self.bus:
            self.bus.close()

