import random
from typing import Dict, Optional

from .state_models import TrafficCounts, RoadVehicleCounts, EmergencyInfo, Road

class FakeYOLOGenerator:
    """
    Generates synthetic per-road vehicle counts each second.
    Can inject an emergency at a configured time for a given road.
    """

    def __init__(self, emergency_at_sec: Optional[int] = 90, emergency_road: Road = Road.south):
        self.emergency_at_sec = emergency_at_sec
        self.emergency_road = emergency_road
        self._t = 0
        # Base rates per road and vehicle type to shape traffic
        self._base_profiles = {
            Road.north: {"car": 4, "bike": 3, "bus": 1, "truck": 1, "lorry": 0, "auto": 2},
            Road.east:  {"car": 2, "bike": 2, "bus": 0, "truck": 0, "lorry": 0, "auto": 1},
            Road.south: {"car": 6, "bike": 4, "bus": 1, "truck": 1, "lorry": 0, "auto": 3},
            Road.west:  {"car": 3, "bike": 2, "bus": 0, "truck": 0, "lorry": 0, "auto": 1},
        }

    def reset(self):
        self._t = 0

    def _rand_count(self, base: int) -> int:
        # Random variation around base, non-negative
        return max(0, int(random.gauss(mu=base, sigma=max(1, base * 0.3))))

    def next_counts(self) -> TrafficCounts:
        self._t += 1
        road_counts = {}
        for road, profile in self._base_profiles.items():
            road_counts[road.value] = RoadVehicleCounts(
                car=self._rand_count(profile["car"]),
                bike=self._rand_count(profile["bike"]),
                bus=self._rand_count(profile["bus"]),
                truck=self._rand_count(profile["truck"]),
                lorry=self._rand_count(profile["lorry"]),
                auto=self._rand_count(profile["auto"]),
            )
        return TrafficCounts(**road_counts)

    def peek_counts(self) -> TrafficCounts:
        # Produce counts without advancing time
        road_counts = {}
        for road, profile in self._base_profiles.items():
            road_counts[road.value] = RoadVehicleCounts(
                car=self._rand_count(profile["car"]),
                bike=self._rand_count(profile["bike"]),
                bus=self._rand_count(profile["bus"]),
                truck=self._rand_count(profile["truck"]),
                lorry=self._rand_count(profile["lorry"]),
                auto=self._rand_count(profile["auto"]),
            )
        return TrafficCounts(**road_counts)

    def current_emergency(self) -> EmergencyInfo:
        if self.emergency_at_sec is not None and self._t >= self.emergency_at_sec:
            return EmergencyInfo(active=True, road=self.emergency_road)
        return EmergencyInfo(active=False, road=None)
