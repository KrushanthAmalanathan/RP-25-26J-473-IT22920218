import asyncio
from typing import Dict, Optional, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from controller.state_models import StatusResponse, EmergencyInfo, SignalState, DecisionInfo, Road
from controller.yolo_fake_generator import FakeYOLOGenerator
from controller.traffic_controller import TrafficController
from controller.memory_store import MemoryStore

app = FastAPI(title="Smart Traffic Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core simulation components
memory_store = MemoryStore("backend/data/memory.json")
generator = FakeYOLOGenerator(emergency_at_sec=90, emergency_road=Road.south)
controller = TrafficController(memory_store=memory_store)

# Runtime state
simulation_active: bool = False
_sim_task: Optional[asyncio.Task] = None
_time_sec: int = 0
_current_status: Optional[StatusResponse] = None

class ControlResponse(BaseModel):
    status: str

@app.get("/api/status", response_model=StatusResponse)
async def get_status():
    global _current_status
    if _current_status is None:
        # Initialize a default status if simulation hasn't started yet
        initial_counts = generator.peek_counts()
        queues = controller.compute_queues(initial_counts)
        _current_status = StatusResponse(
            time=_time_sec,
            counts=initial_counts,
            queues=queues,
            signal=SignalState(greenRoad=controller.current_green, remaining=controller.remaining_green),
            emergency=EmergencyInfo(active=False, road=None),
            decision=DecisionInfo(method="idle", reason="simulation not started")
        )
    return _current_status

@app.get("/api/memory/summary")
async def memory_summary():
    return memory_store.summary()

@app.post("/api/control/start", response_model=ControlResponse)
async def start_simulation():
    global simulation_active, _sim_task
    if simulation_active:
        return ControlResponse(status="already_running")
    simulation_active = True
    _sim_task = asyncio.create_task(_run_loop())
    return ControlResponse(status="started")

@app.post("/api/control/stop", response_model=ControlResponse)
async def stop_simulation():
    global simulation_active, _sim_task
    simulation_active = False
    if _sim_task:
        _sim_task.cancel()
        _sim_task = None
    return ControlResponse(status="stopped")

# WebSocket clients
_ws_clients: List[WebSocket] = []

@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    _ws_clients.append(websocket)
    try:
        while True:
            # Keep the connection alive; server pushes updates separately
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            _ws_clients.remove(websocket)
        except ValueError:
            pass

async def _broadcast_update(status: StatusResponse):
    # Push JSON to all connected clients
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
    global _time_sec, _current_status, simulation_active
    # Reset controller state
    controller.reset()
    # Reset generator time
    generator.reset()
    _time_sec = 0

    try:
        while simulation_active:
            # 1) Generate counts for this tick
            counts = generator.next_counts()
            emergency = generator.current_emergency()

            # 2) Compute queues
            queues = controller.compute_queues(counts)

            # 3) Tick controller: decrement remaining & potentially switch
            decision_info = controller.tick_and_decide(
                time_sec=_time_sec,
                counts=counts,
                queues=queues,
                emergency=emergency,
            )

            # 4) Build status object
            _current_status = StatusResponse(
                time=_time_sec,
                counts=counts,
                queues=queues,
                signal=SignalState(greenRoad=controller.current_green, remaining=controller.remaining_green),
                emergency=emergency,
                decision=decision_info,
            )

            # 5) Broadcast to WebSocket clients
            await _broadcast_update(_current_status)

            # 6) Advance time
            _time_sec += 1
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        # Stopping simulation
        pass
