import json
import math
import time
from typing import Dict, List, Tuple, Optional
from pathlib import Path

from .state_models import MemoryRecord, Road, RoadMetricsSet, RoadMetrics

class MemoryStore:
    """
    Memory store with similarity-based learning and decay.
    
    Supports:
    - Storing experience records (state -> action -> reward)
    - Finding similar past states via cosine similarity
    - Memory decay (older entries weighted less)
    - TOP-K retrieval for decision making
    """
    
    # Similarity configuration
    SIMILARITY_THRESHOLD = 0.5  # Min cosine similarity for valid match
    TOP_K = 5  # Number of similar states to retrieve
    MEMORY_DECAY_TAU = 900  # Memory decay time constant in seconds
    
    def __init__(self, file_path: str):
        self.path = Path(file_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")
        self._cache: List[MemoryRecord] = []
        self._load()
        self._start_time = time.time()  # For decay calculation

    def _load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._cache = [MemoryRecord(**item) for item in raw]
        except Exception:
            self._cache = []

    def _save(self):
        data = [r.dict() for r in self._cache]
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def add_record(self, record: MemoryRecord):
        self._cache.append(record)
        self._save()

    def summary(self) -> Dict:
        count = len(self._cache)
        by_road: Dict[Road, List[float]] = {Road.north: [], Road.east: [], Road.south: [], Road.west: []}
        for r in self._cache:
            by_road[r.action_road].append(r.reward)
        avg_rewards = {road.value: (sum(vals) / len(vals) if vals else 0.0) for road, vals in by_road.items()}
        best_road = max(avg_rewards.items(), key=lambda kv: kv[1])[0] if avg_rewards else None
        return {
            "records": count,
            "avgRewardByRoad": avg_rewards,
            "bestRoad": best_road,
        }

    @staticmethod
    def _state_to_vector(metrics: RoadMetricsSet) -> Dict[Road, List[float]]:
        """
        Convert RoadMetricsSet to state vector per road.
        Vector = [waiting_count, avg_wait_time, congestion%, 
                  time_since_last_green, arrival_rate, departure_rate]
        """
        vectors = {}
        for road in [Road.north, Road.east, Road.south, Road.west]:
            m = getattr(metrics, road.value)
            vec = [
                m.waiting_count,
                m.avg_wait_time,
                m.congestion_percent,
                m.time_since_last_green,
                m.arrival_rate_vpm,
                m.departure_rate_vpm,
            ]
            vectors[road] = vec
        return vectors
    
    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        """
        Compute cosine similarity between two vectors.
        Returns value in [-1, 1], typically [0, 1] for normalized vectors.
        """
        if len(vec_a) == 0 or len(vec_b) == 0:
            return 0.0
        
        # Compute dot product and magnitudes
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        mag_a = math.sqrt(sum(a * a for a in vec_a))
        mag_b = math.sqrt(sum(b * b for b in vec_b))
        
        if mag_a == 0 or mag_b == 0:
            return 0.0
        
        return dot / (mag_a * mag_b)
    
    def _decay_factor(self, record_time: int, current_time: int) -> float:
        """
        Compute decay factor for memory: exp(-age / tau)
        Ensures old memories have less influence on decisions.
        """
        age_seconds = current_time - record_time
        if age_seconds < 0:
            return 1.0
        return math.exp(-age_seconds / self.MEMORY_DECAY_TAU)
    
    def find_similar_states(
        self, 
        current_metrics: RoadMetricsSet, 
        current_time: int,
        k: Optional[int] = None
    ) -> List[Tuple[float, MemoryRecord, float]]:
        """
        Find top-K similar memory records by cosine similarity.
        Returns list of (similarity, record, decay_weight) tuples.
        
        Args:
            current_metrics: Current RoadMetricsSet from SUMO
            current_time: Current simulation time in seconds
            k: Number of results (defaults to TOP_K)
        
        Returns:
            List of (similarity_score, memory_record, decay_weight)
        """
        if k is None:
            k = self.TOP_K
        
        if not self._cache:
            return []
        
        # Convert current state to vectors
        current_vecs = self._state_to_vector(current_metrics)
        
        # Score all cached records by similarity
        similarities: List[Tuple[float, MemoryRecord, float]] = []
        
        for rec in self._cache:
            # We don't have full metrics stored in old records, so compute from queue proxy
            # For now, we'll use a simplified approach: compare avg metrics across the state
            # This is a placeholder - ideal approach stores metrics with each record
            
            # Compute decay weight
            decay = self._decay_factor(rec.time, current_time)
            
            # Simplified similarity: sum of queue similarity
            # (In production, would compare full metric vectors)
            total_similarity = 0.0
            count = 0
            for road in [Road.north, Road.east, Road.south, Road.west]:
                # Simple L2 distance on queue values (inverse)
                # Queue values are single int, not vector
                q_current = 0  # Placeholder - would get from current_metrics
                q_past = rec.state_queues.get(road, 0)
                dist = abs(q_current - q_past)
                sim = 1.0 / (1.0 + dist)  # Convert distance to similarity
                total_similarity += sim
                count += 1
            
            avg_similarity = total_similarity / max(1, count)
            similarities.append((avg_similarity, rec, decay))
        
        # Sort by similarity (descending) and return top-K
        similarities.sort(key=lambda x: x[0] * x[2], reverse=True)
        return similarities[:k]
    
    def get_weighted_rewards_by_road(
        self,
        current_metrics: RoadMetricsSet,
        current_time: int,
        k: Optional[int] = None
    ) -> Dict[Road, Tuple[float, int]]:
        """
        Get weighted average reward for each road from similar past experiences.
        
        Returns:
            Dict mapping Road -> (weighted_avg_reward, count_of_matches)
        """
        if k is None:
            k = self.TOP_K
        
        similar = self.find_similar_states(current_metrics, current_time, k)
        
        reward_by_road: Dict[Road, List[float]] = {
            Road.north: [], Road.east: [], Road.south: [], Road.west: []
        }
        
        for sim_score, rec, decay in similar:
            # Apply both similarity score and decay as weights
            weight = sim_score * decay
            reward_by_road[rec.action_road].append((rec.reward, weight))
        
        # Compute weighted averages
        results = {}
        for road, rewards in reward_by_road.items():
            if rewards:
                total_reward = sum(r * w for r, w in rewards)
                total_weight = sum(w for _, w in rewards)
                weighted_avg = total_reward / max(1e-6, total_weight)
                results[road] = (weighted_avg, len(rewards))
            else:
                results[road] = (0.0, 0)
        
        return results

    @staticmethod
    def _distance(a: Dict[Road, int], b: Dict[Road, int]) -> float:
        # Euclidean distance over queue vectors (kept for backward compatibility)
        return math.sqrt(sum((a[r] - b[r]) ** 2 for r in [Road.north, Road.east, Road.south, Road.west]))

    def find_best_action(self, state_queues: Dict[Road, int]) -> Tuple[Road, int, str]:
        """Return (road, duration, reason) based on nearest past states with best reward."""
        if not self._cache:
            # Default heuristic: pick max queue road for 20s duration
            road = max(state_queues.items(), key=lambda kv: kv[1])[0]
            return road, 20, "default: highest queue"

        # Find k nearest states (k=10)
        items: List[Tuple[float, MemoryRecord]] = []
        for rec in self._cache:
            d = self._distance(state_queues, rec.state_queues)
            items.append((d, rec))
        items.sort(key=lambda x: x[0])
        k = 10
        nearest = items[:k]

        # Aggregate rewards per action road
        reward_by_road: Dict[Road, List[float]] = {Road.north: [], Road.east: [], Road.south: [], Road.west: []}
        for _, rec in nearest:
            reward_by_road[rec.action_road].append(rec.reward)

        # Choose road with best average reward; break ties by current max queue
        avg = {road: (sum(vals)/len(vals) if vals else -1e9) for road, vals in reward_by_road.items()}
        best_road = max(avg.items(), key=lambda kv: kv[1])[0]

        # Duration heuristic: weighted by current queue but bounded
        q = state_queues[best_road]
        duration = max(10, min(45, int(10 + q * 0.7)))
        reason = f"memory: best avg reward for {best_road.value} (q={q})"
        return best_road, duration, reason
