from typing import Dict, Optional, Tuple

from .state_models import Road, TrafficCounts, EmergencyInfo, DecisionInfo, MemoryRecord
from .memory_store import MemoryStore

class TrafficController:
    def __init__(self, memory_store: MemoryStore):
        self.memory = memory_store
        self.weights = {"bike": 1, "car": 2, "auto": 2, "bus": 4, "truck": 4, "lorry": 4}
        self.current_green: Road = Road.south
        self.remaining_green: int = 0
        # For reward calculation
        self._last_action_road: Optional[Road] = None
        self._last_action_duration: int = 0
        self._pre_action_queues: Optional[Dict[Road, int]] = None

        # Decision cycle in seconds
        self.decision_cycle: int = 5
        self._since_last_decision: int = 0

    def reset(self):
        self.current_green = Road.south
        self.remaining_green = 0
        self._last_action_road = None
        self._last_action_duration = 0
        self._pre_action_queues = None
        self._since_last_decision = 0

    def compute_queues(self, counts: TrafficCounts) -> Dict[Road, int]:
        queues: Dict[Road, int] = {}
        for road in [Road.north, Road.east, Road.south, Road.west]:
            rc = getattr(counts, road.value)
            q = (
                rc.bike * self.weights["bike"] +
                rc.car * self.weights["car"] +
                rc.auto * self.weights["auto"] +
                rc.bus * self.weights["bus"] +
                rc.truck * self.weights["truck"] +
                rc.lorry * self.weights["lorry"]
            )
            queues[road] = q
        return queues

    def _decide_next(self, queues: Dict[Road, int]) -> Tuple[Road, int, str]:
        road, duration, reason = self.memory.find_best_action(queues)
        return road, duration, reason

    def _reward(self, before: Dict[Road, int], after: Dict[Road, int], acted_road: Road) -> float:
        # Reward: reduction on acted road minus average increase elsewhere
        delta_acted = before[acted_road] - after[acted_road]
        others = [r for r in [Road.north, Road.east, Road.south, Road.west] if r != acted_road]
        delta_others = sum(after[r] - before[r] for r in others) / max(1, len(others))
        return float(delta_acted - 0.5 * delta_others)

    def tick_and_decide(self, time_sec: int, counts: TrafficCounts, queues: Dict[Road, int], emergency: EmergencyInfo) -> DecisionInfo:
        # Decrement remaining green
        if self.remaining_green > 0:
            self.remaining_green -= 1
        self._since_last_decision += 1

        # Emergency preemption: switch within ~5 seconds
        if emergency.active and emergency.road is not None:
            if self.current_green != emergency.road and (self.remaining_green <= 4 or self._since_last_decision >= self.decision_cycle):
                # Finish reward for previous action if any
                if self._last_action_road is not None and self._pre_action_queues is not None:
                    reward = self._reward(self._pre_action_queues, queues, self._last_action_road)
                    rec = MemoryRecord(
                        time=time_sec,
                        state_queues=self._pre_action_queues,
                        action_road=self._last_action_road,
                        action_duration=self._last_action_duration,
                        reward=reward,
                        reason="phase_end",
                    )
                    self.memory.add_record(rec)

                # Switch immediately
                self.current_green = emergency.road
                self.remaining_green = max(10, self.decision_cycle)
                self._last_action_road = self.current_green
                self._last_action_duration = self.remaining_green
                self._pre_action_queues = queues.copy()
                self._since_last_decision = 0
                return DecisionInfo(method="emergency", reason=f"emergency on {emergency.road.value}, preemption active")

        # Normal decision at cycle boundary or when green ends
        if self.remaining_green <= 0 or self._since_last_decision >= self.decision_cycle:
            # Finish reward for previous action
            if self._last_action_road is not None and self._pre_action_queues is not None:
                reward = self._reward(self._pre_action_queues, queues, self._last_action_road)
                rec = MemoryRecord(
                    time=time_sec,
                    state_queues=self._pre_action_queues,
                    action_road=self._last_action_road,
                    action_duration=self._last_action_duration,
                    reward=reward,
                    reason="phase_end",
                )
                self.memory.add_record(rec)

            # Decide next
            next_road, duration, reason = self._decide_next(queues)
            self.current_green = next_road
            self.remaining_green = duration
            self._last_action_road = self.current_green
            self._last_action_duration = self.remaining_green
            self._pre_action_queues = queues.copy()
            self._since_last_decision = 0
            return DecisionInfo(method="memory", reason=reason)

        # Continue current phase
        return DecisionInfo(method="hold", reason=f"holding {self.current_green.value}")
