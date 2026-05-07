from typing import Dict, Optional, Tuple, Any

from .state_models import Road, TrafficCounts, EmergencyInfo, DecisionInfo
from .multi_agent_dqn import MultiAgentManager, example_junction_config


class TrafficController:
    """
    Traffic Controller using Option-3 Multi-Agent DQN (MultiAgentManager).

    - Uses Sri Lanka-aware priority weights for queues (bus=5).
    - Emergency preemption remains highest priority.
    - Decision is made by DQN: agent_manager.decide("J1", obs) -> (action_idx, duration, reason, metrics)
    """

    def __init__(self):
        # Queue weights (Sri Lanka-aware)
        self.weights = {"bike": 1, "car": 2, "auto": 2, "bus": 5, "truck": 4, "lorry": 4}

        # Signal state
        self.current_green: Road = Road.j8_south_entry
        self.remaining_green: int = 0

        # Decision cycle in seconds
        self.decision_cycle: int = 5
        self._since_last_decision: int = 0

        # DQN Multi-Agent Manager (for now, using J1 mapping; extend to J2/J3 later)
        self.agent_manager = MultiAgentManager(example_junction_config())

        # Mapping between agent action index and Road
        self._idx_to_road = [
            Road.west_entry,
            Road.j1_north_entry,
            Road.j8_north_entry,
            Road.j8_east_entry,
            Road.j8_south_entry
        ]
        self._road_to_idx = {r: i for i, r in enumerate(self._idx_to_road)}

        # Junction ID (set to J1 for now; Nimz can extend to J2/J3 later)
        self.junction_id = "J1"

    def reset(self):
        self.current_green = Road.j8_south_entry
        self.remaining_green = 0
        self._since_last_decision = 0

    def compute_queues(self, counts: TrafficCounts) -> Dict[Road, int]:
        """
        Priority-weighted queue score (used for quick status display / debugging).
        DQN itself uses per-vehicle-type counts in `obs`.
        """
        queues: Dict[Road, int] = {}
        for road in Road:
            rc = getattr(counts, road.value)
            q = (
                rc.bike * self.weights["bike"] +
                rc.car * self.weights["car"] +
                rc.auto * self.weights["auto"] +
                rc.bus * self.weights["bus"] +
                rc.truck * self.weights["truck"] +
                rc.lorry * self.weights["lorry"]
            )
            queues[road] = int(q)
        return queues

    def _build_obs(self, counts: TrafficCounts, emergency: EmergencyInfo) -> Dict[str, Any]:
        """
        Build observation dict in the format expected by MultiAgentManager.decide()

        obs = {
          "approaches": {
              "N": {"bike":int,"car":int,"auto":int,"bus":int,"truck":int,"lorry":int},
              "E": {...},
              "S": {...},
              "W": {...}
          },
          "current_green_index": int,
          "remaining_green": int,
          "emergency": bool,
          "emergency_index": int
        }
        """
        # Convert TrafficCounts into per-approach vehicle-type dict
        approaches = {}

        # IMPORTANT: keys here must match your junction config order.
        road_key_map = {
            "W": Road.west_entry,
            "J1N": Road.j1_north_entry,
            "J8N": Road.j8_north_entry,
            "J8E": Road.j8_east_entry,
            "J8S": Road.j8_south_entry,
        }
        
        for key, road in road_key_map.items():
            rc = getattr(counts, road.value)
            approaches[key] = {
                "bike": int(rc.bike),
                "car": int(rc.car),
                "auto": int(rc.auto),
                "bus": int(rc.bus),
                "truck": int(rc.truck),
                "lorry": int(rc.lorry),
            }

        current_green_index = self._road_to_idx.get(self.current_green, 2)  # default south

        em_active = bool(emergency.active and emergency.road is not None)
        em_idx = 0
        if em_active and emergency.road is not None:
            em_idx = self._road_to_idx.get(emergency.road, 0)

        return {
            "approaches": approaches,
            "current_green_index": int(current_green_index),
            "remaining_green": int(self.remaining_green),
            "emergency": em_active,
            "emergency_index": int(em_idx),
        }

    def _apply_action(self, action_idx: int, duration: int) -> Tuple[Road, int]:
        """
        Map DQN action index to a Road + apply chosen duration.
        """
        idx = max(0, min(action_idx, len(self._idx_to_road) - 1))
        next_road = self._idx_to_road[idx]
        self.current_green = next_road
        self.remaining_green = int(duration)
        self._since_last_decision = 0
        return next_road, self.remaining_green

    def tick_and_decide(
        self,
        time_sec: int,
        counts: TrafficCounts,
        queues: Dict[Road, int],
        emergency: EmergencyInfo
    ) -> DecisionInfo:
        """
        Called every simulation second.
        - Decrements remaining green
        - Handles emergency preemption (fast switch)
        - At decision cycle or phase end, asks DQN for next action
        """

        # Decrement remaining green
        if self.remaining_green > 0:
            self.remaining_green -= 1
        self._since_last_decision += 1

        # Build obs for the agent
        obs = self._build_obs(counts, emergency)

        # Emergency preemption: switch within ~5 seconds
        if obs["emergency"] is True and emergency.road is not None:
            # only preempt if different road and near cycle boundary
            if self.current_green != emergency.road and (
                self.remaining_green <= 4 or self._since_last_decision >= self.decision_cycle
            ):
                # Let agent manager handle emergency override decision (it returns action/duration too)
                action_idx, duration, reason, metrics = self.agent_manager.decide(self.junction_id, obs)

                # Apply action
                self._apply_action(action_idx, duration)

                # If your DecisionInfo model supports metrics, use:
                # return DecisionInfo(method="emergency", reason=reason, metrics=metrics)
                return DecisionInfo(method="emergency", reason=reason)

        # Normal decision at cycle boundary or when green ends
        if self.remaining_green <= 0 or self._since_last_decision >= self.decision_cycle:
            action_idx, duration, reason, metrics = self.agent_manager.decide(self.junction_id, obs)

            self._apply_action(action_idx, duration)

            # If your DecisionInfo supports metrics, use:
            # return DecisionInfo(method="dqn", reason=reason, metrics=metrics)
            return DecisionInfo(method="dqn", reason=reason)

        # Continue current phase
        return DecisionInfo(method="hold", reason=f"holding {self.current_green.value}")