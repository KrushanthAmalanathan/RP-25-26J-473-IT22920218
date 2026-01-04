from typing import Dict, Optional, Tuple
import time

from .state_models import Road, TrafficCounts, EmergencyInfo, DecisionInfo, MemoryRecord, RoadMetricsSet
from .memory_store import MemoryStore
from .prediction import TrafficPredictor

class TrafficController:
    """
    Enhanced traffic signal controller with:
    - Composite scoring function (queue + wait + fairness + congestion)
    - Memory-based learning with similarity matching and decay
    - Dynamic green duration based on waiting vehicles
    - Fairness guarantee (starvation protection)
    - Short-term traffic prediction (queue trends, heavy traffic probability)
    - Decision explanations with prediction context
    """
    
    # === Scoring Configuration ===
    # Weights for composite scoring function
    WEIGHT_QUEUE = 1.0      # Penalize roads with many waiting vehicles
    WEIGHT_WAIT = 0.8       # Penalize roads with high avg wait time
    WEIGHT_FAIR = 0.6       # Penalize roads that haven't had green recently
    WEIGHT_CONG = 0.4       # Penalize congested roads
    WEIGHT_SWITCH = 1.2     # Penalty for rapidly switching phases
    WEIGHT_PRED = 0.3       # Prediction-based bias for heavy traffic
    
    # === Green Duration Configuration ===
    MIN_GREEN = 10          # Minimum green duration (seconds)
    MAX_GREEN = 60          # Maximum green duration (seconds)
    ALPHA = 1.0             # Coefficient for waiting_count contribution
    BETA = 0.5              # Coefficient for avg_wait_time contribution
    GAP_OUT_THRESHOLD = 3   # Seconds without waiting vehicles before ending green
    
    # === Fairness Configuration ===
    MAX_RED_TIME = 90       # Max time a road can stay red (starvation protection)
    
    # === Memory-Based Learning Configuration ===
    MEMORY_CONFIDENCE_THRESHOLD = 0.7  # Min similarity for memory-based decision
    MEMORY_DECAY_TAU = 900  # Memory decay time constant (seconds)
    
    def __init__(self, memory_store: MemoryStore):
        self.memory = memory_store
        self.predictor = TrafficPredictor()  # Initialize prediction engine
        self.weights = {"bike": 1, "car": 2, "auto": 2, "bus": 4, "truck": 4, "lorry": 4}
        self.current_green: Road = Road.south
        self.remaining_green: int = 0
        
        # Manual control state
        self.mode: str = "AUTO"  # "AUTO" or "MANUAL"
        self.manual_command: Optional[str] = None  # "NS_GREEN" | "EW_GREEN" | "ALL_RED"
        self.manual_until: Optional[float] = None  # Expiry timestamp
        self.manual_start_time: Optional[float] = None  # Start timestamp for logging
        
        # For reward calculation
        self._last_action_road: Optional[Road] = None
        self._last_action_duration: int = 0
        self._pre_action_queues: Optional[Dict[Road, int]] = None
        self._pre_action_metrics: Optional[RoadMetricsSet] = None
        self._last_predictions: Optional[Dict] = None
        
        # Decision cycle in seconds
        self.decision_cycle: int = 5
        self._since_last_decision: int = 0
        
        # Track time of last green per road
        self._last_green_time: Dict[Road, int] = {
            Road.north: -9999,
            Road.east: -9999,
            Road.south: 0,  # Start with south green
            Road.west: -9999,
        }
        
        # Track consecutive seconds without waiting vehicles
        self._no_wait_counter: Dict[Road, int] = {
            road: 0 for road in [Road.north, Road.east, Road.south, Road.west]
        }
        
        # For decision logging
        self._last_decision_method: str = "none"
        self._last_decision_reason: str = ""
        self._start_time = time.time()

    def reset(self):
        self.current_green = Road.south
        self.remaining_green = 0
        self._last_action_road = None
        self._last_action_duration = 0
        self._pre_action_queues = None
        self._pre_action_metrics = None
        self._last_predictions = None
        self.predictor.reset()
        
        # Reset manual control state
        self.mode = "AUTO"
        self.manual_command = None
        self.manual_until = None
        self.manual_start_time = None
        
        for road in [Road.north, Road.east, Road.south, Road.west]:
            self._last_green_time[road] = 0 if road == Road.south else -9999
            self._no_wait_counter[road] = 0

        self._last_action_road = None
        self._last_action_duration = 0
        self._pre_action_queues = None
        self._pre_action_metrics = None
        self._since_last_decision = 0
        self._last_green_time = {
            Road.north: -9999,
            Road.east: -9999,
            Road.south: 0,
            Road.west: -9999,
        }
        self._no_wait_counter = {road: 0 for road in [Road.north, Road.east, Road.south, Road.west]}
    
    def set_manual_mode(self, command: str, duration: int, current_time: float) -> None:
        """Activate manual override mode with specified command and duration."""
        self.mode = "MANUAL"
        self.manual_command = command
        self.manual_until = current_time + duration
        self.manual_start_time = current_time
    
    def cancel_manual(self) -> None:
        """Cancel manual override and return to AUTO mode."""
        self.mode = "AUTO"
        self.manual_command = None
        self.manual_until = None
        self.manual_start_time = None
    
    def check_manual_expired(self, current_time: float) -> bool:
        """Check if manual override has expired. Returns True if expired."""
        if self.mode == "MANUAL" and self.manual_until is not None:
            if current_time >= self.manual_until:
                self.cancel_manual()
                return True
        return False
    
    def get_manual_remaining(self, current_time: float) -> int:
        """Get remaining seconds for manual override."""
        if self.mode == "MANUAL" and self.manual_until is not None:
            remaining = max(0, int(self.manual_until - current_time))
            return remaining
        return 0


    def compute_queues(self, counts: TrafficCounts) -> Dict[Road, int]:
        """Compute weighted queue lengths from vehicle counts."""
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
    
    def _composite_score(
        self,
        road: Road,
        metrics: RoadMetricsSet,
        current_time: int,
        predictions: Optional[Dict] = None
    ) -> float:
        """
        Compute composite score for a road using multiple metrics.
        
        score = w_queue * waiting_count
               + w_wait * avg_waiting_time
               + w_fair * time_since_last_green
               + w_cong * congestion_percent
               + w_pred * prediction_bias
               - w_switch * switching_penalty
        
        Higher score = higher priority for green.
        """
        m = getattr(metrics, road.value)
        
        # Switching penalty: discourage rapid oscillation
        switch_penalty = (
            self.WEIGHT_SWITCH if self.current_green == road else 0.0
        )
        
        # Prediction bias: additive bias for heavy traffic forecast
        pred_bias = 0.0
        if predictions:
            pred_bias = self.predictor.get_prediction_bias_for_road(road, predictions)
        
        score = (
            self.WEIGHT_QUEUE * m.waiting_count
            + self.WEIGHT_WAIT * m.avg_wait_time
            + self.WEIGHT_FAIR * m.time_since_last_green
            + self.WEIGHT_CONG * m.congestion_percent
            + self.WEIGHT_PRED * pred_bias
            - switch_penalty
        )
        
        return score
    
    def _calculate_dynamic_green_duration(
        self,
        road: Road,
        metrics: RoadMetricsSet
    ) -> int:
        """
        Calculate green duration dynamically based on waiting vehicles and wait time.
        
        green_time = min_green + alpha * waiting_count + beta * avg_wait_time
        Clamped to [min_green, max_green].
        """
        m = getattr(metrics, road.value)
        
        duration = (
            self.MIN_GREEN
            + self.ALPHA * m.waiting_count
            + self.BETA * m.avg_wait_time
        )
        
        # Clamp to bounds
        duration = max(self.MIN_GREEN, min(self.MAX_GREEN, int(duration)))
        
        return duration
    
    def _apply_gap_out_rule(
        self,
        road: Road,
        metrics: RoadMetricsSet,
        remaining_green: int
    ) -> Optional[int]:
        """
        Apply gap-out rule: end green early if no waiting vehicles for X seconds.
        
        Returns modified remaining_green, or None if gap-out not triggered.
        """
        m = getattr(metrics, road.value)
        
        # Track no-wait counter
        if m.waiting_count == 0:
            self._no_wait_counter[road] += 1
        else:
            self._no_wait_counter[road] = 0
        
        # If we've had X seconds of no waiting vehicles, end green early
        if self._no_wait_counter[road] >= self.GAP_OUT_THRESHOLD:
            return 0  # End green immediately
        
        return None
    
    def _apply_starvation_protection(
        self,
        metrics: RoadMetricsSet,
        current_time: int
    ) -> Optional[Road]:
        """
        Apply starvation protection: force service to any road that's been red > MAX_RED_TIME.
        
        Returns Road that must be served next, or None if no starvation.
        """
        for road in [Road.north, Road.east, Road.south, Road.west]:
            if road == self.current_green:
                continue  # Already green
            
            time_since_green = current_time - self._last_green_time[road]
            if time_since_green > self.MAX_RED_TIME:
                return road
        
        return None
    
    def _decide_next_with_memory_learning(
        self,
        metrics: RoadMetricsSet,
        current_time: int,
        starvation_road: Optional[Road] = None,
        predictions: Optional[Dict] = None
    ) -> Tuple[Road, int, str, str]:
        """
        Decide next green road using memory-based learning with similarity matching.
        Incorporates traffic prediction bias for heavy traffic forecasting.
        
        Returns (road, duration, method, reason)
        method in ["memory", "fallback", "starvation"]
        """
        
        # === STARVATION PROTECTION (highest priority) ===
        if starvation_road is not None:
            duration = self._calculate_dynamic_green_duration(starvation_road, metrics)
            reason = f"Starvation protection: {starvation_road.value} red for >{self.MAX_RED_TIME}s"
            return starvation_road, duration, "starvation", reason
        
        # === MEMORY-BASED LEARNING ===
        # Try to find similar past states and use their learned rewards
        similar_rewards = self.memory.get_weighted_rewards_by_road(metrics, current_time)
        
        # Check if we have high-confidence matches
        max_similarity = max((count for _, count in similar_rewards.values()), default=0)
        
        if max_similarity >= self.MEMORY_CONFIDENCE_THRESHOLD:
            # Choose road with highest weighted reward from memory
            best_road = max(
                similar_rewards.items(),
                key=lambda kv: kv[1][0]  # Use reward value, not count
            )[0]
            
            reward_value, match_count = similar_rewards[best_road]
            duration = self._calculate_dynamic_green_duration(best_road, metrics)
            
            # Add prediction context if available
            pred_context = ""
            if predictions and best_road in predictions:
                pred = predictions[best_road]
                if "congestion_level" in pred:
                    pred_context = f", predicted={pred['congestion_level']}"
            
            reason = f"Memory-based: {best_road.value} (reward={reward_value:.1f}, matches={match_count}{pred_context})"
            return best_road, duration, "memory", reason
        
        # === FALLBACK: COMPOSITE SCORING (with prediction bias) ===
        scores = {}
        for road in [Road.north, Road.east, Road.south, Road.west]:
            scores[road] = self._composite_score(road, metrics, current_time, predictions)
        
        best_road = max(scores.items(), key=lambda kv: kv[1])[0]
        duration = self._calculate_dynamic_green_duration(best_road, metrics)
        score_value = scores[best_road]
        
        # Add prediction context if available
        pred_context = ""
        if predictions and best_road in predictions:
            pred = predictions[best_road]
            if "congestion_level" in pred:
                pred_context = f", predicted={pred['congestion_level']}"
        
        reason = f"Composite score: {best_road.value} (score={score_value:.1f}{pred_context})"
        
        return best_road, duration, "fallback", reason

    def _reward(self, before: Dict[Road, int], after: Dict[Road, int], acted_road: Road) -> float:
        """
        Compute reward: reduction on acted road minus average increase elsewhere.
        """
        delta_acted = before[acted_road] - after[acted_road]
        others = [r for r in [Road.north, Road.east, Road.south, Road.west] if r != acted_road]
        delta_others = sum(after[r] - before[r] for r in others) / max(1, len(others))
        return float(delta_acted - 0.5 * delta_others)

    def tick_and_decide(
        self,
        time_sec: int,
        counts: TrafficCounts,
        queues: Dict[Road, int],
        metrics: RoadMetricsSet,
        emergency: EmergencyInfo,
        predictions: Optional[Dict] = None
    ) -> DecisionInfo:
        """
        Main decision logic called every simulation step.
        
        Priority: Emergency > Manual > Starvation > Memory > Composite
        Returns DecisionInfo with method and reason.
        """
        current_real_time = time.time()
        
        # Store predictions for use in scoring
        if predictions:
            self._last_predictions = predictions
        
        # Decrement remaining green
        if self.remaining_green > 0:
            self.remaining_green -= 1
        self._since_last_decision += 1

        # === EMERGENCY PREEMPTION (highest priority) ===
        if emergency.active and emergency.road is not None:
            # Emergency overrides manual mode
            if self.mode == "MANUAL":
                self.cancel_manual()
            
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

                # Switch immediately to emergency road
                self.current_green = emergency.road
                self.remaining_green = max(10, self.decision_cycle)
                self._last_action_road = self.current_green
                self._last_action_duration = self.remaining_green
                self._pre_action_queues = queues.copy()
                self._pre_action_metrics = metrics
                self._last_green_time[emergency.road] = time_sec
                self._since_last_decision = 0
                
                reason = f"Emergency preemption: ambulance on {emergency.road.value}"
                self._last_decision_method = "emergency"
                self._last_decision_reason = reason
                return DecisionInfo(method="emergency", reason=reason)
        
        # === MANUAL OVERRIDE (second priority) ===
        if self.mode == "MANUAL":
            # Check if manual has expired
            if self.check_manual_expired(current_real_time):
                # Expired, continue to normal decision
                reason = "Manual expired, returning to AUTO"
                self._last_decision_method = "manual_expired"
                self._last_decision_reason = reason
                # Continue to normal decision logic below
            else:
                # Apply manual command
                manual_remaining = self.get_manual_remaining(current_real_time)
                
                if self.manual_command == "ALL_RED":
                    # Keep all red - handled by app_sumo.py
                    reason = f"Manual ALL_RED ({manual_remaining}s remaining)"
                    self._last_decision_method = "manual"
                    self._last_decision_reason = reason
                    return DecisionInfo(method="manual", reason=reason)
                
                elif self.manual_command == "NS_GREEN":
                    # Force North or South green alternating
                    if self.remaining_green <= 0 or self._since_last_decision >= self.decision_cycle:
                        # Switch between N and S
                        if self.current_green == Road.north:
                            next_road = Road.south
                        else:
                            next_road = Road.north
                        
                        self.current_green = next_road
                        self.remaining_green = min(30, manual_remaining)
                        self._last_green_time[next_road] = time_sec
                        self._since_last_decision = 0
                    
                    reason = f"Manual NS_GREEN: {self.current_green.value} ({manual_remaining}s remaining)"
                    self._last_decision_method = "manual"
                    self._last_decision_reason = reason
                    return DecisionInfo(method="manual", reason=reason)
                
                elif self.manual_command == "EW_GREEN":
                    # Force East or West green alternating
                    if self.remaining_green <= 0 or self._since_last_decision >= self.decision_cycle:
                        # Switch between E and W
                        if self.current_green == Road.east:
                            next_road = Road.west
                        else:
                            next_road = Road.east
                        
                        self.current_green = next_road
                        self.remaining_green = min(30, manual_remaining)
                        self._last_green_time[next_road] = time_sec
                        self._since_last_decision = 0
                    
                    reason = f"Manual EW_GREEN: {self.current_green.value} ({manual_remaining}s remaining)"
                    self._last_decision_method = "manual"
                    self._last_decision_reason = reason
                    return DecisionInfo(method="manual", reason=reason)

        # === NORMAL DECISION AT CYCLE BOUNDARY ===
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

            # Check for starvation
            starvation_road = self._apply_starvation_protection(metrics, time_sec)
            
            # Decide next road using memory-based learning with fallback (with prediction context)
            next_road, duration, decision_method, reason = self._decide_next_with_memory_learning(
                metrics, time_sec, starvation_road, predictions
            )
            
            self.current_green = next_road
            self.remaining_green = duration
            self._last_action_road = self.current_green
            self._last_action_duration = self.remaining_green
            self._pre_action_queues = queues.copy()
            self._pre_action_metrics = metrics
            self._last_green_time[next_road] = time_sec
            self._since_last_decision = 0
            
            self._last_decision_method = decision_method
            self._last_decision_reason = reason
            return DecisionInfo(method=decision_method, reason=reason)
        
        # === GAP-OUT RULE ===
        # Check if we should end green early
        gap_out_result = self._apply_gap_out_rule(self.current_green, metrics, self.remaining_green)
        if gap_out_result == 0:
            # End green immediately
            self.remaining_green = 0
            reason = f"Gap-out: no waiting vehicles on {self.current_green.value}"
            return DecisionInfo(method="gap_out", reason=reason)

        # === CONTINUE CURRENT PHASE ===
        return DecisionInfo(method="hold", reason=f"holding {self.current_green.value}")

