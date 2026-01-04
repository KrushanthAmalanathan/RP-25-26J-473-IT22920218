import asyncio
import sys
import os
import json
from typing import Dict, Optional, List
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from controller.state_models import StatusResponse, EmergencyInfo, SignalState, DecisionInfo, Road, RoadMetricsSet, PredictionSet, PredictionMetrics
from controller.sumo_connector import SUMOConnector
from controller.traffic_controller import TrafficController
from controller.memory_store import MemoryStore
from controller.prediction import TrafficPredictor

app = FastAPI(title="Smart Traffic Backend (SUMO)", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SUMO configuration path
SUMO_CFG = os.path.join(os.path.dirname(__file__), "..", "sumo", "junction.sumocfg")

# Metrics logging path
METRICS_LOG_PATH = os.path.join(os.path.dirname(__file__), "data", "logs.jsonl")

# Ensure logs directory exists
os.makedirs(os.path.dirname(METRICS_LOG_PATH), exist_ok=True)

# Core simulation components
memory_store = MemoryStore("backend/data/memory.json")
sumo_connector = None  # Initialized on start
controller = TrafficController(memory_store=memory_store)
predictor = TrafficPredictor()

# Runtime state
simulation_active: bool = False
_sim_task: Optional[asyncio.Task] = None
_time_sec: int = 0
_current_status: Optional[StatusResponse] = None

class ControlResponse(BaseModel):
    status: str
    message: Optional[str] = None

def _log_metrics(time_sec: int, metrics: RoadMetricsSet, signal_state: SignalState, predictions: Optional[Dict] = None):
    """Log metrics and predictions to JSONL file for analysis"""
    try:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "simulation_time": time_sec,
            "metrics": metrics.dict(),
            "signal": {
                "green_road": signal_state.greenRoad.value,
                "remaining_seconds": signal_state.remaining
            }
        }
        
        # Add prediction data if available
        if predictions:
            log_entry["predictions"] = {}
            for road, pred in predictions.items():
                log_entry["predictions"][road.value] = {
                    "queue_trend": pred.get("queue_trend", "stable"),
                    "heavy_traffic_probability": pred.get("heavy_traffic_probability", 0.0),
                    "congestion_level": pred.get("congestion_level", "LOW"),
                    "predicted_eta_clear_seconds": pred.get("predicted_eta_clear_seconds", 0),
                }
        
        with open(METRICS_LOG_PATH, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"Warning: Could not log metrics: {e}")

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

# === Manual Control API Endpoints ===

class ModeRequest(BaseModel):
    mode: str  # "AUTO" or "MANUAL"

class ModeResponse(BaseModel):
    mode: str
    manual_active: bool
    manual_command: Optional[str] = None
    remaining_seconds: int = 0

class ManualApplyRequest(BaseModel):
    command: str  # "NS_GREEN" | "EW_GREEN" | "ALL_RED"
    duration: int  # 10-120 seconds

class ManualApplyResponse(BaseModel):
    status: str
    message: str
    command: str
    duration: int

@app.get("/api/control/mode", response_model=ModeResponse)
async def get_control_mode():
    """Get current control mode (AUTO or MANUAL)"""
    import time
    current_time = time.time()
    
    remaining = 0
    if controller.mode == "MANUAL" and controller.manual_until:
        remaining = max(0, int(controller.manual_until - current_time))
    
    return ModeResponse(
        mode=controller.mode,
        manual_active=(controller.mode == "MANUAL"),
        manual_command=controller.manual_command,
        remaining_seconds=remaining
    )

@app.post("/api/control/mode", response_model=ModeResponse)
async def set_control_mode(request: ModeRequest):
    """Switch between AUTO and MANUAL mode"""
    import time
    current_time = time.time()
    
    if request.mode not in ["AUTO", "MANUAL"]:
        raise ValueError("Mode must be 'AUTO' or 'MANUAL'")
    
    if request.mode == "AUTO":
        controller.cancel_manual()
        _log_manual_event("mode_change", "AUTO", None, 0, "user_request")
    else:
        # Just set mode to MANUAL, command will be applied separately
        controller.mode = "MANUAL"
        _log_manual_event("mode_change", "MANUAL", None, 0, "user_request")
    
    remaining = 0
    if controller.mode == "MANUAL" and controller.manual_until:
        remaining = max(0, int(controller.manual_until - current_time))
    
    return ModeResponse(
        mode=controller.mode,
        manual_active=(controller.mode == "MANUAL"),
        manual_command=controller.manual_command,
        remaining_seconds=remaining
    )

@app.post("/api/control/manual/apply", response_model=ManualApplyResponse)
async def apply_manual_control(request: ManualApplyRequest):
    """Apply a manual control command with duration"""
    import time
    current_time = time.time()
    
    # Validate command
    valid_commands = ["NS_GREEN", "EW_GREEN", "ALL_RED"]
    if request.command not in valid_commands:
        return ManualApplyResponse(
            status="error",
            message=f"Invalid command. Must be one of: {', '.join(valid_commands)}",
            command=request.command,
            duration=request.duration
        )
    
    # Validate duration
    if not (10 <= request.duration <= 120):
        return ManualApplyResponse(
            status="error",
            message="Duration must be between 10 and 120 seconds",
            command=request.command,
            duration=request.duration
        )
    
    # Apply manual control
    controller.set_manual_mode(request.command, request.duration, current_time)
    _log_manual_event("manual_apply", "MANUAL", request.command, request.duration, "user_request")
    
    return ManualApplyResponse(
        status="success",
        message=f"Manual control applied: {request.command} for {request.duration}s",
        command=request.command,
        duration=request.duration
    )

@app.post("/api/control/manual/cancel", response_model=ControlResponse)
async def cancel_manual_control():
    """Cancel manual override and return to AUTO mode"""
    if controller.mode != "MANUAL":
        return ControlResponse(status="info", message="Not in manual mode")
    
    controller.cancel_manual()
    _log_manual_event("manual_cancel", "AUTO", None, 0, "user_request")
    
    return ControlResponse(status="success", message="Manual control cancelled, returned to AUTO mode")

def _log_manual_event(event_type: str, mode: str, command: Optional[str], duration: int, reason: str):
    """Log manual control events to JSONL file"""
    try:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "simulation_time": _time_sec,
            "event_type": event_type,  # mode_change, manual_apply, manual_expire, manual_cancel, emergency_interrupt
            "mode": mode,
            "command": command,
            "duration": duration,
            "reason": reason
        }
        
        with open(METRICS_LOG_PATH, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except Exception as e:
        print(f"Warning: Could not log manual event: {e}")

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

def _convert_predictions_to_prediction_set(predictions: Optional[Dict]) -> PredictionSet:
    """Convert prediction dictionary to PredictionSet model."""
    if not predictions:
        return PredictionSet()
    
    def to_metrics(pred_dict: dict) -> PredictionMetrics:
        return PredictionMetrics(
            queue_trend=pred_dict.get("queue_trend", "stable"),
            arrivals_10s=pred_dict.get("arrivals_10s", 0.0),
            arrivals_30s=pred_dict.get("arrivals_30s", 0.0),
            heavy_traffic_probability=pred_dict.get("heavy_traffic_probability", 0.0),
            congestion_level=pred_dict.get("congestion_level", "LOW"),
            predicted_eta_clear_seconds=pred_dict.get("predicted_eta_clear_seconds", 0),
        )
    
    return PredictionSet(
        north=to_metrics(predictions.get(Road.north, {})),
        east=to_metrics(predictions.get(Road.east, {})),
        south=to_metrics(predictions.get(Road.south, {})),
        west=to_metrics(predictions.get(Road.west, {})),
    )

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
    predictor.reset()
    _time_sec = 0

    try:
        while simulation_active and sumo_connector.is_running():
            import time
            current_real_time = time.time()
            
            # 1) Step SUMO simulation
            sumo_connector.step()
            
            # 2) Get vehicle counts from SUMO
            counts = sumo_connector.get_vehicle_counts()
            emergency = sumo_connector.detect_emergency()

            # 3) Update vehicle tracking for metrics
            sumo_connector._update_vehicle_tracking()

            # 4) Compute queues
            queues = controller.compute_queues(counts)

            # 5) Compute metrics
            metrics = sumo_connector.compute_metrics()

            # 6) Compute predictions using queue history
            predictions = predictor.predict(metrics)

            # 7) Tick controller: decide next phase with metrics and predictions
            decision_info = controller.tick_and_decide(
                time_sec=_time_sec,
                counts=counts,
                queues=queues,
                metrics=metrics,
                emergency=emergency,
                predictions=predictions,
            )
            
            # 8) Send phase command to SUMO
            # Handle manual ALL_RED command specially
            if controller.mode == "MANUAL" and controller.manual_command == "ALL_RED":
                sumo_connector.set_all_red(duration=1)
            else:
                sumo_connector.set_green_phase(controller.current_green, controller.remaining_green)
            
            # Check if manual expired and log
            if controller.check_manual_expired(current_real_time):
                _log_manual_event("manual_expire", "AUTO", None, 0, "duration_expired")

            # 9) Build manual info
            from controller.state_models import ManualInfo
            manual_info = ManualInfo(
                active=(controller.mode == "MANUAL"),
                command=controller.manual_command,
                remaining_seconds=controller.get_manual_remaining(current_real_time)
            )
            
            # 10) Get actual SUMO green state
            actual_green_info = sumo_connector.get_actual_green_info()
            
            # 11) Build status object with metrics, predictions, manual info, and SUMO actual state
            _current_status = StatusResponse(
                time=_time_sec,
                counts=counts,
                queues=queues,
                signal=SignalState(greenRoad=controller.current_green, remaining=controller.remaining_green),
                emergency=emergency,
                decision=decision_info,
                metrics=metrics,
                prediction=_convert_predictions_to_prediction_set(predictions),
                mode=controller.mode,
                manual=manual_info,
                sumo_phase_index=actual_green_info["sumo_phase_index"],
                sumo_tls_state=actual_green_info["sumo_tls_state"],
                actual_green_group=actual_green_info["actual_green_group"],
                actual_green_roads=actual_green_info["actual_green_roads"],
            )

            # 12) Log metrics and predictions every decision cycle
            if _time_sec % controller.decision_cycle == 0:
                _log_metrics(_time_sec, metrics, _current_status.signal, predictions)

            # 13) Broadcast to WebSocket clients
            await _broadcast_update(_current_status)

            # 14) Advance time
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
