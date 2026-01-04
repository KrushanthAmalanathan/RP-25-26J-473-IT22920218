import os
import sys
import traci
from typing import Dict, Optional, List, Set
from collections import defaultdict
from datetime import datetime

from .state_models import TrafficCounts, RoadVehicleCounts, EmergencyInfo, Road, RoadMetrics, RoadMetricsSet

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
        self.tl_id = "center"  # Traffic light junction ID
        self._t = 0
        self.connected = False
        
        # Vehicle type mapping
        self.type_map = {
            "passenger": "car",
            "bicycle": "bike",
            "bus": "bus",
            "truck": "truck",
            "trailer": "lorry",
            "taxi": "auto",
        }
        
        # Road edge IDs (incoming edges)
        self.edge_map = {
            Road.north: "north_in",
            Road.east: "east_in",
            Road.south: "south_in",
            Road.west: "west_in",
        }
        
        # Metrics tracking per road
        self.vehicle_waiting_times: Dict[Road, Dict[str, float]] = {
            road: {} for road in [Road.north, Road.east, Road.south, Road.west]
        }
        self.vehicle_in_edge: Dict[Road, Set[str]] = {
            road: set() for road in [Road.north, Road.east, Road.south, Road.west]
        }
        # Sliding window for arrival/departure rates (last 60 seconds)
        self.arrival_history: Dict[Road, List[int]] = {
            road: [] for road in [Road.north, Road.east, Road.south, Road.west]
        }
        self.departure_history: Dict[Road, List[int]] = {
            road: [] for road in [Road.north, Road.east, Road.south, Road.west]
        }
        # Track when each road last received green
        self.last_green_time: Dict[Road, int] = {
            road: -9999 for road in [Road.north, Road.east, Road.south, Road.west]
        }
        # Track cleared vehicles in current interval
        self.cleared_last_interval: Dict[Road, int] = {
            road: 0 for road in [Road.north, Road.east, Road.south, Road.west]
        }
        
        # Phase mapping (NS vs EW)
        self._ns_phase: int = 0  # Default North-South phase index
        self._ew_phase: int = 2  # Default East-West phase index
        self._active_program_id: Optional[str] = None

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
            
            # Use actual traffic light program instead of "off"
            logics = traci.trafficlight.getAllProgramLogics(self.tl_id)
            if logics:
                program_id = logics[0].programID
                traci.trafficlight.setProgram(self.tl_id, program_id)
                self._active_program_id = program_id
                print(f"✓ Using TLS program: {program_id}")
            else:
                print(f"WARNING: No TLS program logics found for {self.tl_id}")
            
            # Infer phase mapping
            self._infer_phase_map()
            
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
        # Reset all tracking data
        for road in [Road.north, Road.east, Road.south, Road.west]:
            self.vehicle_waiting_times[road].clear()
            self.vehicle_in_edge[road].clear()
            self.arrival_history[road].clear()
            self.departure_history[road].clear()
            self.last_green_time[road] = -9999
            self.cleared_last_interval[road] = 0
        self.connect()

    def step(self):
        """Advance SUMO simulation by one step (1 second)"""
        if not self.connected:
            raise RuntimeError("SUMO not connected")
        traci.simulationStep()
        self._t += 1

    def get_vehicle_counts(self) -> TrafficCounts:
        """
        Count vehicles on each incoming edge by type.
        Returns TrafficCounts matching backend format.
        """
        counts = {
            Road.north: {"car": 0, "bike": 0, "bus": 0, "truck": 0, "lorry": 0, "auto": 0},
            Road.east: {"car": 0, "bike": 0, "bus": 0, "truck": 0, "lorry": 0, "auto": 0},
            Road.south: {"car": 0, "bike": 0, "bus": 0, "truck": 0, "lorry": 0, "auto": 0},
            Road.west: {"car": 0, "bike": 0, "bus": 0, "truck": 0, "lorry": 0, "auto": 0},
        }

        for road, edge_id in self.edge_map.items():
            try:
                vehicle_ids = traci.edge.getLastStepVehicleIDs(edge_id)
                for veh_id in vehicle_ids:
                    veh_class = traci.vehicle.getVehicleClass(veh_id)
                    veh_type = self.type_map.get(veh_class, "car")
                    counts[road][veh_type] += 1
            except Exception as e:
                print(f"Warning: Could not read vehicles on {edge_id}: {e}")

        return TrafficCounts(
            north=RoadVehicleCounts(**counts[Road.north]),
            east=RoadVehicleCounts(**counts[Road.east]),
            south=RoadVehicleCounts(**counts[Road.south]),
            west=RoadVehicleCounts(**counts[Road.west]),
        )

    def detect_emergency(self) -> EmergencyInfo:
        """
        Detect emergency vehicle (e.g., ambulance ID contains 'emergency' or 'ambulance')
        Returns which road it's on.
        """
        for road, edge_id in self.edge_map.items():
            try:
                vehicle_ids = traci.edge.getLastStepVehicleIDs(edge_id)
                for veh_id in vehicle_ids:
                    if "emergency" in veh_id.lower() or "ambulance" in veh_id.lower():
                        return EmergencyInfo(active=True, road=road)
            except Exception:
                pass
        return EmergencyInfo(active=False, road=None)

    def set_green_phase(self, road: Road, duration: int):
        """
        Set traffic light to green for specified road using inferred phase mapping.
        Verifies that the phase was applied correctly.
        """
        # Determine target phase using inferred mapping
        if road in (Road.north, Road.south):
            phase_idx = self._ns_phase
        else:  # east or west
            phase_idx = self._ew_phase
        
        try:
            # Apply phase
            traci.trafficlight.setPhase(self.tl_id, phase_idx)
            traci.trafficlight.setPhaseDuration(self.tl_id, duration)
            
            # Verify phase was applied
            applied = traci.trafficlight.getPhase(self.tl_id)
            state = traci.trafficlight.getRedYellowGreenState(self.tl_id)
            
            if applied != phase_idx:
                print(f"WARNING: Phase not applied. Requested={phase_idx}, Applied={applied}, state={state}")
            else:
                print(f"✓ Applied phase={applied} for {road.value} (state={state})")
            
            # Update last green time for this road
            self.last_green_time[road] = self._t
            self.last_green_time[self._get_opposite_road(road)] = self._t
        except Exception as e:
            print(f"Warning: Could not set traffic light phase: {e}")
    
    def set_all_red(self, duration: int = 1):
        """
        Set all traffic lights to red for safety.
        Used for manual ALL_RED command and safe transitions.
        """
        try:
            # SUMO uses state strings where each character represents a signal
            # 'r' = red, 'G' = green, 'y' = yellow
            # Standard 4-way junction has 12 signals
            all_red_state = "rrrrrrrrrrrr"
            traci.trafficlight.setRedYellowGreenState(self.tl_id, all_red_state)
        except Exception as e:
            print(f"Warning: Could not set all-red phase: {e}")
    
    def apply_safe_transition(self, from_road: Road, to_road: Road, to_duration: int):
        """
        Safely transition between signal phases.
        If switching between NS <-> EW, insert 1s all-red phase for safety.
        Otherwise, directly switch.
        """
        # Determine if this is a NS <-> EW transition
        ns_roads = {Road.north, Road.south}
        ew_roads = {Road.east, Road.west}
        
        from_is_ns = from_road in ns_roads
        to_is_ns = to_road in ns_roads
        from_is_ew = from_road in ew_roads
        to_is_ew = to_road in ew_roads
        
        # If switching between NS and EW, insert all-red
        if (from_is_ns and to_is_ew) or (from_is_ew and to_is_ns):
            self.set_all_red(duration=1)
            # Note: Caller should wait 1 second before setting next green
        else:
            # Same direction group, direct switch
            self.set_green_phase(to_road, to_duration)
    
    def _get_opposite_road(self, road: Road) -> Road:
        """Get opposite road (North<->South, East<->West)"""
        opposites = {
            Road.north: Road.south,
            Road.south: Road.north,
            Road.east: Road.west,
            Road.west: Road.east,
        }
        return opposites[road]
    
    def _update_vehicle_tracking(self):
        """
        Update per-vehicle waiting time tracking and arrival/departure counts.
        Must be called before computing metrics.
        """
        for road, edge_id in self.edge_map.items():
            try:
                current_vehicles = set(traci.edge.getLastStepVehicleIDs(edge_id))
                previous_vehicles = self.vehicle_in_edge[road]
                
                # Departures: vehicles that were in edge but are no longer
                departures = previous_vehicles - current_vehicles
                self.cleared_last_interval[road] = len(departures)
                self.departure_history[road].append(self._time_sec)
                
                # Arrivals: vehicles that are now in edge but weren't before
                arrivals = current_vehicles - previous_vehicles
                self.arrival_history[road].append(self._time_sec + len(arrivals))
                
                # Update waiting time for current vehicles
                for veh_id in current_vehicles:
                    try:
                        speed = traci.vehicle.getSpeed(veh_id)
                        is_waiting = speed < self.WAITING_SPEED_THRESHOLD
                        
                        if veh_id not in self.vehicle_waiting_times[road]:
                            self.vehicle_waiting_times[road][veh_id] = 0.0
                        
                        # Accumulate waiting time if vehicle is stopped or slow
                        if is_waiting:
                            self.vehicle_waiting_times[road][veh_id] += 1.0
                    except Exception:
                        pass
                
                # Remove waiting time records for vehicles that left
                for veh_id in departures:
                    if veh_id in self.vehicle_waiting_times[road]:
                        del self.vehicle_waiting_times[road][veh_id]
                
                # Update current vehicles set
                self.vehicle_in_edge[road] = current_vehicles
            except Exception as e:
                print(f"Warning: Could not update vehicle tracking for {road.value}: {e}")
    
    def compute_metrics(self) -> RoadMetricsSet:
        """
        Compute all metrics for each road.
        Returns RoadMetricsSet with metrics for North, East, South, West.
        """
        metrics = {}
        
        for road in [Road.north, Road.east, Road.south, Road.west]:
            edge_id = self.edge_map[road]
            
            # Get current vehicles on edge
            try:
                current_vehicles = traci.edge.getLastStepVehicleIDs(edge_id)
            except Exception:
                current_vehicles = []
            
            # 1) Waiting vehicle count (halting or speed < threshold)
            waiting_count = 0
            for veh_id in current_vehicles:
                try:
                    speed = traci.vehicle.getSpeed(veh_id)
                    if speed == 0.0 or speed < self.WAITING_SPEED_THRESHOLD:
                        waiting_count += 1
                except Exception:
                    pass
            
            # 2) Average waiting time in seconds
            wait_times = self.vehicle_waiting_times[road]
            avg_wait_time = (
                sum(wait_times.values()) / len(wait_times)
                if len(wait_times) > 0
                else 0.0
            )
            
            # 3) Cleared vehicles in last interval
            cleared_last_interval = self.cleared_last_interval[road]
            
            # 4 & 5) Arrival and departure rates (vehicles per minute)
            # Use sliding window of last 60 seconds
            current_time = self._t
            window_start = current_time - 60
            
            arrivals_in_window = sum(
                1 for t in self.arrival_history[road] if t > window_start
            )
            departures_in_window = sum(
                1 for t in self.departure_history[road] if t > window_start
            )
            
            # Compute rates: (count / time_window_in_minutes)
            time_window_minutes = max(1.0, (current_time - window_start) / 60.0)
            arrival_rate_vpm = arrivals_in_window / time_window_minutes
            departure_rate_vpm = departures_in_window / time_window_minutes
            
            # 6) Time since last green (seconds)
            time_since_last_green = current_time - self.last_green_time[road]
            
            # 7) Congestion percentage
            congestion_percent = min(
                100.0,
                (waiting_count / self.MAX_QUEUE_PER_ROAD) * 100.0
            )
            
            # 8) ETA to clear queue (seconds)
            # discharge_rate = departures per second
            discharge_rate = max(
                departure_rate_vpm / 60.0,  # Convert VPM to vehicles/second
                0.1  # Minimum to avoid division by zero
            )
            eta_clear_seconds = waiting_count / discharge_rate
            
            metrics[road] = RoadMetrics(
                waiting_count=waiting_count,
                avg_wait_time=round(avg_wait_time, 2),
                cleared_last_interval=cleared_last_interval,
                arrival_rate_vpm=round(arrival_rate_vpm, 2),
                departure_rate_vpm=round(departure_rate_vpm, 2),
                time_since_last_green=round(time_since_last_green, 2),
                congestion_percent=round(congestion_percent, 2),
                eta_clear_seconds=round(eta_clear_seconds, 2),
            )
            
            # Reset cleared counter for next interval
            self.cleared_last_interval[road] = 0
        
        return RoadMetricsSet(
            north=metrics[Road.north],
            east=metrics[Road.east],
            south=metrics[Road.south],
            west=metrics[Road.west],
        )

    @property
    def current_time(self) -> int:
        """Current simulation time in seconds"""
        return self._t
    
    @property
    def _time_sec(self) -> int:
        """Alias for current_time for backward compatibility"""
        return self._t

    def is_running(self) -> bool:
        """Check if simulation is still running"""
        if not self.connected:
            return False
        try:
            min_expected_vehicles = traci.simulation.getMinExpectedNumber()
            return min_expected_vehicles > 0
        except Exception:
            return False
    
    def _infer_phase_map(self):
        """
        Infer which phase indices correspond to NS and EW green.
        Uses controlled links and incoming edge IDs to determine mapping.
        """
        try:
            logics = traci.trafficlight.getAllProgramLogics(self.tl_id)
            if not logics:
                print("WARNING: No program logics found, using defaults NS=0, EW=2")
                return
            
            phases = logics[0].phases
            if not phases:
                print("WARNING: No phases found, using defaults NS=0, EW=2")
                return
            
            # Get controlled links
            controlled_links = traci.trafficlight.getControlledLinks(self.tl_id)
            
            # Map link indices to incoming edges
            link_to_edge = {}
            for link_idx, link_data in enumerate(controlled_links):
                if link_data:  # link_data is a list of tuples (incoming_lane, outgoing_lane, via_lane)
                    incoming_lane = link_data[0][0]  # First tuple, first element
                    edge_id = incoming_lane.rsplit('_', 1)[0]  # Remove lane index
                    link_to_edge[link_idx] = edge_id
            
            # Score each phase
            ns_edges = {"north_in", "south_in"}
            ew_edges = {"east_in", "west_in"}
            
            best_ns_phase = 0
            best_ns_score = 0
            best_ew_phase = 2
            best_ew_score = 0
            
            for phase_idx, phase in enumerate(phases):
                state = phase.state
                ns_score = 0
                ew_score = 0
                
                # Count green signals for NS and EW
                for link_idx, signal in enumerate(state):
                    if signal in ('G', 'g'):  # Green signal
                        edge_id = link_to_edge.get(link_idx, "")
                        if edge_id in ns_edges:
                            ns_score += 1
                        elif edge_id in ew_edges:
                            ew_score += 1
                
                # Update best phases
                if ns_score > best_ns_score:
                    best_ns_score = ns_score
                    best_ns_phase = phase_idx
                if ew_score > best_ew_score:
                    best_ew_score = ew_score
                    best_ew_phase = phase_idx
            
            self._ns_phase = best_ns_phase
            self._ew_phase = best_ew_phase
            print(f"✓ Inferred phase mapping: NS={self._ns_phase}, EW={self._ew_phase}")
            
        except Exception as e:
            print(f"WARNING: Phase inference failed ({e}), using defaults NS=0, EW=2")
            self._ns_phase = 0
            self._ew_phase = 2
    
    def get_actual_green_info(self) -> dict:
        """
        Get actual SUMO traffic light state information.
        Returns dict with phase_index, state_string, and actual_green_roads.
        """
        try:
            phase_idx = traci.trafficlight.getPhase(self.tl_id)
            state = traci.trafficlight.getRedYellowGreenState(self.tl_id)
            
            # Determine actual green group
            if phase_idx == self._ns_phase:
                actual_green_group = "NS"
                actual_green_roads = ["north", "south"]
            elif phase_idx == self._ew_phase:
                actual_green_group = "EW"
                actual_green_roads = ["east", "west"]
            else:
                actual_green_group = "TRANSITION"
                actual_green_roads = []
            
            return {
                "sumo_phase_index": phase_idx,
                "sumo_tls_state": state,
                "actual_green_group": actual_green_group,
                "actual_green_roads": actual_green_roads,
            }
        except Exception as e:
            print(f"Warning: Could not get actual green info: {e}")
            return {
                "sumo_phase_index": -1,
                "sumo_tls_state": "unknown",
                "actual_green_group": "UNKNOWN",
                "actual_green_roads": [],
            }
