import os
import sys
import traci
from typing import Dict, Optional, List, Set, Tuple
from collections import defaultdict
from datetime import datetime
import logging

from .state_models import TrafficCounts, RoadVehicleCounts, EmergencyInfo, Road, RoadMetrics, RoadMetricsSet
from .sumo_road_map import SUMO_ROADS

logger = logging.getLogger(__name__)

class SUMOConnector:
    """
    Connects to SUMO via TraCI to:
    1. Read real-time vehicle counts per approach
    2. Control traffic light phases based on adaptive decisions
    3. Detect emergency vehicles
    4. Compute per-road metrics (waiting time, congestion, etc.)
    """

    # Configuration constants
    MAX_QUEUE_PER_ROAD = 40  # vehicles
    WAITING_SPEED_THRESHOLD = 2.0  # m/s

    def __init__(self, sumo_cfg_path: str, use_gui: bool = True):
        self.sumo_cfg = sumo_cfg_path
        self.use_gui = use_gui
        self._t = 0
        self.connected = False
        
        # Vehicle type mapping fallback
        self.type_map = {
            "passenger": "car",
            "bicycle": "bike",
            "bus": "bus",
            "truck": "truck",
            "trailer": "lorry",
            "taxi": "auto",
        }
        
        # Road edge IDs (incoming edges)
        self.edge_map: Dict[Road, str] = {}
        self.junction_ids: Set[str] = set()
        
        for r_id, r_data in SUMO_ROADS.items():
            self.edge_map[Road(r_id)] = r_data["entryEdge"]
            self.junction_ids.add(r_data["junctionId"])
        
        # Metrics tracking per road
        self.vehicle_waiting_times: Dict[Road, Dict[str, float]] = {road: {} for road in self.edge_map.keys()}
        self.vehicle_in_edge: Dict[Road, Set[str]] = {road: set() for road in self.edge_map.keys()}
        self.arrival_history: Dict[Road, List[int]] = {road: [] for road in self.edge_map.keys()}
        self.departure_history: Dict[Road, List[int]] = {road: [] for road in self.edge_map.keys()}
        self.last_green_time: Dict[Road, int] = {road: -9999 for road in self.edge_map.keys()}
        self.cleared_last_interval: Dict[Road, int] = {road: 0 for road in self.edge_map.keys()}
        
        # Link mapping per junction
        self._link_to_edge: Dict[str, Dict[int, str]] = defaultdict(dict)
        self._edge_to_links: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
        self._manual_last_effective_command: Optional[str] = None
        self._active_program_ids: Dict[str, str] = {}

    def connect(self):
        """Start SUMO simulation via TraCI"""
        if self.connected:
            return
        
        sumo_binary = "sumo-gui" if self.use_gui else "sumo"
        sumo_cmd = [sumo_binary, "-c", self.sumo_cfg, "--start", "--quit-on-end"]
        
        try:
            traci.start(sumo_cmd)
            self.connected = True
            print(f"✓ SUMO connected via TraCI (GUI={self.use_gui})")
            
            # Setup traffic lights for all junctions
            for j_id in self.junction_ids:
                logics = traci.trafficlight.getAllProgramLogics(j_id)
                if logics:
                    program_id = logics[0].programID
                    traci.trafficlight.setProgram(j_id, program_id)
                    self._active_program_ids[j_id] = program_id
                    print(f"✓ Using TLS program for {j_id}: {program_id}")
                else:
                    print(f"WARNING: No TLS program logics found for {j_id}")
            
            self._build_link_maps()
            
        except Exception as e:
            print(f"✗ Failed to connect to SUMO: {e}")
            raise

    def disconnect(self):
        """Close SUMO simulation"""
        if self.connected:
            traci.close()
            self.connected = False
            print("✓ SUMO disconnected")

    def reset(self):
        """Reset simulation (reconnect)"""
        self.disconnect()
        self._t = 0
        for road in self.edge_map.keys():
            self.vehicle_waiting_times[road].clear()
            self.vehicle_in_edge[road].clear()
            self.arrival_history[road].clear()
            self.departure_history[road].clear()
            self.last_green_time[road] = -9999
            self.cleared_last_interval[road] = 0
        self.connect()

    def step(self):
        """Advance SUMO simulation by one step"""
        if not self.connected:
            raise RuntimeError("SUMO not connected")
        traci.simulationStep()
        self._t += 1
        self._update_vehicle_tracking()

    def get_counts(self) -> TrafficCounts:
        """Count vehicles on each incoming edge by type."""
        counts = {
            road: {"car": 0, "bike": 0, "bus": 0, "truck": 0, "lorry": 0, "auto": 0}
            for road in self.edge_map.keys()
        }

        for road, edge_id in self.edge_map.items():
            try:
                vehicle_ids = traci.edge.getLastStepVehicleIDs(edge_id)
                for veh_id in vehicle_ids:
                    # Prefer exact type ID matching the route file
                    veh_type = traci.vehicle.getTypeID(veh_id)
                    if veh_type not in counts[road]:
                        # Fallback to class mapping
                        veh_class = traci.vehicle.getVehicleClass(veh_id)
                        veh_type = self.type_map.get(veh_class, "car")
                    
                    if veh_type in counts[road]:
                        counts[road][veh_type] += 1
            except Exception as e:
                pass # Ignore if edge is missing or vehicle departed

        return TrafficCounts(
            west_entry=RoadVehicleCounts(**counts[Road.west_entry]),
            j1_north_entry=RoadVehicleCounts(**counts[Road.j1_north_entry]),
            j8_north_entry=RoadVehicleCounts(**counts[Road.j8_north_entry]),
            j8_east_entry=RoadVehicleCounts(**counts[Road.j8_east_entry]),
            j8_south_entry=RoadVehicleCounts(**counts[Road.j8_south_entry]),
        )

    def detect_emergency(self) -> EmergencyInfo:
        for road, edge_id in self.edge_map.items():
            try:
                vehicle_ids = traci.edge.getLastStepVehicleIDs(edge_id)
                for veh_id in vehicle_ids:
                    if "emergency" in veh_id.lower() or "ambulance" in veh_id.lower():
                        return EmergencyInfo(active=True, road=road)
            except Exception:
                pass
        return EmergencyInfo(active=False, road=None)

    def _build_link_maps(self):
        """Build mapping between controlled link indices and incoming edges per junction."""
        self._link_to_edge.clear()
        self._edge_to_links.clear()
        for j_id in self.junction_ids:
            try:
                controlled_links = traci.trafficlight.getControlledLinks(j_id)
                for link_idx, link_data in enumerate(controlled_links):
                    if not link_data:
                        continue
                    incoming_lane = link_data[0][0]
                    edge_id = incoming_lane.rsplit('_', 1)[0]
                    self._link_to_edge[j_id][link_idx] = edge_id
                    self._edge_to_links[j_id][edge_id].append(link_idx)
            except Exception as e:
                print(f"WARNING: Could not build controlled-link map for {j_id}: {e}")

    def _road_to_edge(self, road: Road) -> str:
        return self.edge_map[road]

    def _edge_to_road_name(self, edge_id: str) -> Optional[str]:
        for road, mapped_edge in self.edge_map.items():
            if mapped_edge == edge_id:
                return road.value
        return None

    def _build_custom_state(self, j_id: str, green_edges: Set[str]) -> str:
        link_map = self._link_to_edge.get(j_id, {})
        link_count = max(len(link_map), 0)
        if link_count == 0:
            link_count = len(traci.trafficlight.getRedYellowGreenState(j_id))
            
        state_chars = ['r'] * link_count
        for idx, edge_id in link_map.items():
            if edge_id in green_edges and idx < len(state_chars):
                state_chars[idx] = 'G'
        return ''.join(state_chars)

    def _set_custom_green_edges(self, green_edges: Set[str], duration: int, effective_command: str):
        """Apply green state across all relevant junctions"""
        try:
            for j_id in self.junction_ids:
                state = self._build_custom_state(j_id, green_edges)
                traci.trafficlight.setRedYellowGreenState(j_id, state)
                traci.trafficlight.setPhaseDuration(j_id, max(1, duration))
            
            self._manual_last_effective_command = effective_command

            active_roads = []
            for edge in green_edges:
                road_name = self._edge_to_road_name(edge)
                if road_name:
                    active_roads.append(road_name)
                    for road, mapped_edge in self.edge_map.items():
                        if mapped_edge == edge:
                            self.last_green_time[road] = self._t
            print(f"✓ Applied custom state {effective_command}: roads={active_roads}")
        except Exception as e:
            print(f"Warning: Could not apply custom green edges {green_edges}: {e}")

    def apply_manual_command(self, command: str, duration: int):
        normalized = (command or '').upper()

        if normalized == 'ALL_RED':
            self.set_all_red(duration=max(1, duration))
            self._manual_last_effective_command = normalized
            return

        # Translate semantic commands to specific roads depending on the new mapping.
        # Since the new map is asymmetrical, NS/EW fallback to specific edges.
        edges = set()
        if "N" in normalized or "NS" in normalized:
            edges.add(self._road_to_edge(Road.j1_north_entry))
            edges.add(self._road_to_edge(Road.j8_north_entry))
        if "S" in normalized or "NS" in normalized:
            edges.add(self._road_to_edge(Road.j8_south_entry))
        if "E" in normalized or "EW" in normalized:
            edges.add(self._road_to_edge(Road.j8_east_entry))
        if "W" in normalized or "EW" in normalized:
            edges.add(self._road_to_edge(Road.west_entry))

        self._set_custom_green_edges(edges, duration, normalized)

    def set_all_red(self, duration: int = 1):
        try:
            for j_id in self.junction_ids:
                current_len = len(traci.trafficlight.getRedYellowGreenState(j_id))
                all_red_state = "r" * current_len
                traci.trafficlight.setRedYellowGreenState(j_id, all_red_state)
                traci.trafficlight.setPhaseDuration(j_id, max(1, duration))
            self._manual_last_effective_command = "ALL_RED"
        except Exception as e:
            print(f"Warning: Could not set all-red phase: {e}")

    def set_green_phase(self, road: Road, duration: int):
        """
        Set a specific road to green across all relevant junctions.
        """
        try:
            edge_id = self._road_to_edge(road)
            self._set_custom_green_edges({edge_id}, duration, f"AUTO_{road.value}")
        except Exception as e:
            print(f"Warning: Could not set green phase for {road}: {e}")

    def _update_vehicle_tracking(self):
        for road, edge_id in self.edge_map.items():
            try:
                current_vehicles = set(traci.edge.getLastStepVehicleIDs(edge_id))
                previous_vehicles = self.vehicle_in_edge[road]
                
                departures = previous_vehicles - current_vehicles
                self.cleared_last_interval[road] = len(departures)
                for _ in departures:
                    self.departure_history[road].append(self._time_sec)
                
                arrivals = current_vehicles - previous_vehicles
                for _ in arrivals:
                    self.arrival_history[road].append(self._time_sec)
                
                for veh_id in current_vehicles:
                    try:
                        speed = traci.vehicle.getSpeed(veh_id)
                        is_waiting = speed < self.WAITING_SPEED_THRESHOLD
                        
                        if veh_id not in self.vehicle_waiting_times[road]:
                            self.vehicle_waiting_times[road][veh_id] = 0.0
                        
                        if is_waiting:
                            self.vehicle_waiting_times[road][veh_id] += 1.0
                    except Exception:
                        pass
                
                for veh_id in departures:
                    if veh_id in self.vehicle_waiting_times[road]:
                        del self.vehicle_waiting_times[road][veh_id]
                
                self.vehicle_in_edge[road] = current_vehicles
            except Exception:
                pass
    
    def compute_metrics(self) -> RoadMetricsSet:
        metrics = {}
        for road in self.edge_map.keys():
            edge_id = self.edge_map[road]
            try:
                current_vehicles = traci.edge.getLastStepVehicleIDs(edge_id)
            except Exception:
                current_vehicles = []
            
            waiting_count = sum(1 for veh_id in current_vehicles if traci.vehicle.getSpeed(veh_id) < self.WAITING_SPEED_THRESHOLD)
            wait_times = self.vehicle_waiting_times[road]
            avg_wait_time = sum(wait_times.values()) / len(wait_times) if wait_times else 0.0
            
            window_start = self._t - 60
            arrivals_in_window = sum(1 for t in self.arrival_history[road] if t > window_start)
            departures_in_window = sum(1 for t in self.departure_history[road] if t > window_start)
            
            time_window_minutes = max(1.0, (self._t - window_start) / 60.0)
            metrics[road] = RoadMetrics(
                waiting_count=waiting_count,
                avg_wait_time=round(avg_wait_time, 2),
                cleared_last_interval=self.cleared_last_interval[road],
                arrival_rate_vpm=round(arrivals_in_window / time_window_minutes, 2),
                departure_rate_vpm=round(departures_in_window / time_window_minutes, 2),
                time_since_last_green=round(self._t - self.last_green_time[road], 2),
                congestion_percent=round(min(100.0, (waiting_count / self.MAX_QUEUE_PER_ROAD) * 100.0), 2),
                eta_clear_seconds=round(waiting_count / max(departures_in_window / time_window_minutes / 60.0, 0.1), 2),
            )
            self.cleared_last_interval[road] = 0
            
        return RoadMetricsSet(
            west_entry=metrics[Road.west_entry],
            j1_north_entry=metrics[Road.j1_north_entry],
            j8_north_entry=metrics[Road.j8_north_entry],
            j8_east_entry=metrics[Road.j8_east_entry],
            j8_south_entry=metrics[Road.j8_south_entry],
        )

    @property
    def current_time(self) -> int:
        return self._t
    
    @property
    def _time_sec(self) -> int:
        return self._t

    def is_running(self) -> bool:
        if not self.connected:
            return False
        try:
            return traci.simulation.getMinExpectedNumber() > 0
        except Exception:
            return False

    def detect_emergency(self) -> EmergencyInfo:
        """
        Scan all entry roads for emergency vehicles (police, ambulance, firetruck).
        """
        active_emergency = False
        emergency_road = None

        for road, edge_id in self.edge_map.items():
            try:
                vehicle_ids = traci.edge.getLastStepVehicleIDs(edge_id)
                for veh_id in vehicle_ids:
                    vtype = traci.vehicle.getTypeID(veh_id)
                    if vtype in ["police", "ambulance", "firetruck"]:
                        active_emergency = True
                        emergency_road = road
                        break
                if active_emergency:
                    break
            except Exception:
                pass

        return EmergencyInfo(active=active_emergency, road=emergency_road)

    def _is_edge_green(self, edge_id: str) -> bool:
        """Checks if any traffic light link for this edge is currently green across any controlled junction."""
        try:
            for j_id in self.junction_ids:
                state = traci.trafficlight.getRedYellowGreenState(j_id)
                links = self._edge_to_links.get(j_id, {}).get(edge_id, [])
                for link_idx in links:
                    if link_idx < len(state) and state[link_idx] in ('G', 'g'):
                        return True
        except Exception:
            pass
        return False

    def get_actual_green_roads(self) -> List[str]:
        """Returns semantic road IDs that are currently green."""
        green_roads = []
        for road, edge_id in self.edge_map.items():
            if self._is_edge_green(edge_id):
                green_roads.append(road.value)
        return green_roads

    def get_actual_green_group(self) -> str:
        """Returns the name of the last applied command or 'AUTO'."""
        return self._manual_last_effective_command or "AUTO"

    def get_actual_green_info(self) -> Dict:
        """
        Return the current state of traffic lights in SUMO.
        """
        try:
            ref_junc = "J1"
            actual_green_roads = self.get_actual_green_roads()
            
            if ref_junc in self.junction_ids:
                state = traci.trafficlight.getRedYellowGreenState(ref_junc)
                phase = traci.trafficlight.getPhase(ref_junc)
                return {
                    "sumo_phase_index": phase,
                    "sumo_tls_state": state,
                    "actual_green_group": self._manual_last_effective_command or "AUTO",
                    "actual_green_roads": actual_green_roads,
                }
        except Exception:
            pass

        return {
            "sumo_phase_index": -1,
            "sumo_tls_state": "unknown",
            "actual_green_group": "UNKNOWN",
            "actual_green_roads": [],
        }

    def disconnect(self):
        """Close TraCI connection safely."""
        if self.connected:
            try:
                traci.close()
            except Exception:
                pass
            self.connected = False
            print("SUMO disconnected.")
