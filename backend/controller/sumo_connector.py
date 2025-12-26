import os
import sys
import traci
from typing import Dict, Optional
from collections import defaultdict

from .state_models import TrafficCounts, RoadVehicleCounts, EmergencyInfo, Road

class SUMOConnector:
    """
    Connects to SUMO via TraCI to:
    1. Read real-time vehicle counts per approach
    2. Control traffic light phases based on adaptive decisions
    3. Detect emergency vehicles
    """

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
            
            # Set traffic light to manual control (we control phases)
            traci.trafficlight.setProgram(self.tl_id, "off")
            
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
        Set traffic light to green for specified road.
        SUMO phase indices (standard 4-way junction):
        - Phase 0: North-South green
        - Phase 2: East-West green
        """
        # Map road to SUMO phase
        phase_map = {
            Road.north: 0,
            Road.south: 0,
            Road.east: 2,
            Road.west: 2,
        }
        
        phase_idx = phase_map[road]
        
        try:
            # Set phase duration
            traci.trafficlight.setPhase(self.tl_id, phase_idx)
            traci.trafficlight.setPhaseDuration(self.tl_id, duration)
        except Exception as e:
            print(f"Warning: Could not set traffic light phase: {e}")

    @property
    def current_time(self) -> int:
        """Current simulation time in seconds"""
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
