import asyncio
import os
from typing import Dict, Optional, List, Set
from dotenv import load_dotenv

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from controller.state_models import StatusResponse, EmergencyInfo, SignalState, DecisionInfo, Road
from controller.yolo_fake_generator import FakeYOLOGenerator
from controller.traffic_controller import TrafficController
from controller.memory_store import MemoryStore

# Load environment variables
load_dotenv()

app = FastAPI(title="Smart Traffic Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# WebSocket Connection Manager
class ConnectionManager:
    """Manages WebSocket connections and broadcasting."""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket):
        """Accept and store a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
        print(f"Client connected. Total clients: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket."""
        self.active_connections.discard(websocket)
        print(f"Client disconnected. Total clients: {len(self.active_connections)}")
    
    async def broadcast(self, data: dict):
        """Broadcast a message to all connected clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception as e:
                print(f"Error broadcasting to client: {e}")
                disconnected.append(connection)
        
        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)
    
    def get_connection_count(self) -> int:
        """Return the number of active connections."""
        return len(self.active_connections)

# Initialize connection manager
ws_manager = ConnectionManager()

# Core simulation components
memory_store = MemoryStore("data/memory.json")
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

@app.get("/api/ws/status")
async def ws_status():
    """Return WebSocket connection status."""
    return {
        "connected_clients": ws_manager.get_connection_count(),
        "ws_url": "ws://localhost:5000/ws/live"
    }

@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    """
    WebSocket endpoint for live traffic status updates.
    Clients connect here and receive real-time status broadcasts.
    """
    await ws_manager.connect(websocket)
    try:
        # Keep connection alive; updates are sent via _broadcast_update
        while True:
            # Receive and ignore client messages (server-side push only)
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        ws_manager.disconnect(websocket)

async def _broadcast_update(status: StatusResponse):
    """Broadcast status update to all connected WebSocket clients."""
    await ws_manager.broadcast(status.dict())

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
