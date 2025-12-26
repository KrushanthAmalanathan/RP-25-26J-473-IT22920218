import json
import math
from typing import Dict, List, Tuple
from pathlib import Path

from .state_models import MemoryRecord, Road

class MemoryStore:
    def __init__(self, file_path: str):
        self.path = Path(file_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")
        self._cache: List[MemoryRecord] = []
        self._load()

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
    def _distance(a: Dict[Road, int], b: Dict[Road, int]) -> float:
        # Euclidean distance over queue vectors
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
