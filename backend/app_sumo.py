import asyncio
import sys
import os
from typing import Dict, Optional, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from controller.state_models import StatusResponse, EmergencyInfo, SignalState, DecisionInfo, Road
from controller.sumo_connector import SUMOConnector
from controller.traffic_controller import TrafficController
from controller.memory_store import MemoryStore

app = FastAPI(title="Smart Traffic Backend (SUMO)", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SUMO configuration path
SUMO_CFG = os.path.join(os.path.dirname(__file__), "..", "sumo", "junction.sumocfg")

# Core simulation components
memory_store = MemoryStore("backend/data/memory.json")
sumo_connector = None  # Initialized on start
controller = TrafficController(memory_store=memory_store)

# Runtime state
simulation_active: bool = False
_sim_task: Optional[asyncio.Task] = None
_time_sec: int = 0
_current_status: Optional[StatusResponse] = None

class ControlResponse(BaseModel):
    status: str
    message: Optional[str] = None

@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    global _current_status
    if _current_status is None:
        # Return idle status
        from controller.state_models import TrafficCounts, RoadVehicleCounts
        empty_counts = TrafficCounts(
            north=RoadVehicleCounts(),
            east=RoadVehicleCounts(),
            south=RoadVehicleCounts(),
            west=RoadVehicleCounts(),
        )
        _current_status = StatusResponse(
            time=_time_sec,
            counts=empty_counts,
            queues={Road.north: 0, Road.east: 0, Road.south: 0, Road.west: 0},
            signal=SignalState(greenRoad=Road.south, remaining=0),
            emergency=EmergencyInfo(active=False, road=None),
            decision=DecisionInfo(method="idle", reason="simulation not started")
        )
    return _current_status

@app.get("/api/memory/summary")
async def memory_summary():
    return memory_store.summary()

@app.post("/api/control/start", response_model=ControlResponse)
async def start_simulation():
    global simulation_active, _sim_task, sumo_connector
    if simulation_active:
        return ControlResponse(status="already_running")
    
    try:
        # Initialize SUMO connector
        sumo_connector = SUMOConnector(SUMO_CFG, use_gui=True)
        sumo_connector.connect()
        
        simulation_active = True
        _sim_task = asyncio.create_task(_run_loop())
        return ControlResponse(status="started", message="SUMO simulation started with GUI")
    except Exception as e:
        return ControlResponse(status="error", message=f"Failed to start SUMO: {str(e)}")

@app.post("/api/control/stop", response_model=ControlResponse)
async def stop_simulation():
    global simulation_active, _sim_task, sumo_connector
    simulation_active = False
    if _sim_task:
        _sim_task.cancel()
        _sim_task = None
    if sumo_connector:
        sumo_connector.disconnect()
        sumo_connector = None
    return ControlResponse(status="stopped", message="SUMO simulation stopped")

# WebSocket clients
_ws_clients: List[WebSocket] = []

@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            _ws_clients.remove(websocket)
        except ValueError:
            pass

async def _broadcast_update(status: StatusResponse):
    stale: List[WebSocket] = []
    for ws in list(_ws_clients):
        try:
            await ws.send_json(status.dict())
        except Exception:
            stale.append(ws)
    for s in stale:
        try:
            _ws_clients.remove(s)
        except ValueError:
            pass

async def _run_loop():
    global _time_sec, _current_status, simulation_active, sumo_connector
    
    # Reset controller state
    controller.reset()
    _time_sec = 0

    try:
        while simulation_active and sumo_connector.is_running():
            # 1) Step SUMO simulation
            sumo_connector.step()
            
            # 2) Get vehicle counts from SUMO
            counts = sumo_connector.get_vehicle_counts()
            emergency = sumo_connector.detect_emergency()

            # 3) Compute queues
            queues = controller.compute_queues(counts)

            # 4) Tick controller: decide next phase
            decision_info = controller.tick_and_decide(
                time_sec=_time_sec,
                counts=counts,
                queues=queues,
                emergency=emergency,
            )
            
            # 5) Send phase command to SUMO
            sumo_connector.set_green_phase(controller.current_green, controller.remaining_green)

            # 6) Build status object
            _current_status = StatusResponse(
                time=_time_sec,
                counts=counts,
                queues=queues,
                signal=SignalState(greenRoad=controller.current_green, remaining=controller.remaining_green),
                emergency=emergency,
                decision=decision_info,
            )

            # 7) Broadcast to WebSocket clients
            await _broadcast_update(_current_status)

            # 8) Advance time
            _time_sec += 1
            await asyncio.sleep(1)
            
        # Simulation ended
        simulation_active = False
        if sumo_connector:
            sumo_connector.disconnect()
            
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"Error in simulation loop: {e}")
        simulation_active = False
        if sumo_connector:
            sumo_connector.disconnect()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
