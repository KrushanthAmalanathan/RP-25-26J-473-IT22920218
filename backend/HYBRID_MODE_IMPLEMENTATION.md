# Hybrid Input Mode Implementation - TASK 1

## Overview

This implementation integrates YOLO-based vehicle detection from a laptop camera for the WEST road, while maintaining the existing fake data generator for NORTH/EAST/SOUTH roads. The system is fully configurable and includes automatic fallback to fake data if camera fails.

## Components Added

### 1. **Data Provider Abstraction** (`backend/controller/data_provider.py`)

Provides a clean interface for data sources with the following key classes:

#### `RoadDataProvider` (Abstract Base Class)
- `get_counts()` - Returns vehicle counts by type for all roads
- `get_queue_metrics()` - Returns queue lengths (currently returns zeros, can be extended)

#### `HybridProvider` (Implementation)
- **WEST**: Uses YOLO camera if enabled, falls back to fake data automatically
- **NORTH/EAST/SOUTH**: Always uses fake generator (unchanged)
- **Health Status**: Tracks camera status with error counting and fallback logic
- **Error Handling**: Logs warnings but doesn't crash on camera failures

### 2. **State Model Updates** (`backend/controller/state_models.py`)

#### New: `InputHealthInfo` Model
```python
class InputHealthInfo(BaseModel):
    west_source: str         # "camera" or "fake"
    camera_ok: bool          # Camera operational status
    last_camera_ts: float    # Last successful camera read timestamp
    camera_error_count: int  # Number of consecutive camera errors
```

#### Updated: `StatusResponse` Model
- Added `inputs: InputHealthInfo` field to report input source health

### 3. **Backend Integration** (`backend/app_sumo.py`)

#### Environment Configuration
```
USE_CAMERA_WEST=true/false          # Enable/disable camera for WEST
WEST_CAMERA_INDEX=0                 # Camera device index
WEST_MODEL_PATH=backend/models/best.pt  # YOLO model path
WEST_CONF=0.30                      # YOLO confidence threshold
```

#### Initialization
- Loads HybridProvider with configuration from `.env` file
- Logs configuration at startup
- Gracefully handles missing environment variables

#### Simulation Loop Integration
- **Step 2a**: After SUMO provides all counts, override WEST with camera data if enabled
- **Step 9a**: Build input health info before status update
- Maintains all existing algorithm logic unchanged

#### Cleanup
- Properly shuts down camera/YOLO resources on simulation stop
- Logs any errors during shutdown

## Configuration

### Quick Start
1. **Disable Camera (Default - Safe)**
   ```bash
   # Use default .env - camera disabled
   # All data comes from SUMO (unchanged behavior)
   python run_with_sumo.py
   ```

2. **Enable Camera for WEST**
   ```bash
   # Edit .env:
   USE_CAMERA_WEST=true
   WEST_CAMERA_INDEX=0        # or 1, 2, etc. for external cameras
   WEST_MODEL_PATH=backend/models/best.pt
   WEST_CONF=0.30
   
   # Run:
   python run_with_sumo.py
   ```

### Environment Variables
All can be set in `backend/.env`:

| Variable | Default | Notes |
|----------|---------|-------|
| `USE_CAMERA_WEST` | `false` | Set to `true` to enable camera |
| `WEST_CAMERA_INDEX` | `0` | Device index (0=built-in, 1=external) |
| `WEST_MODEL_PATH` | `backend/models/best.pt` | Path to YOLO weights |
| `WEST_CONF` | `0.30` | Detection confidence (0.0-1.0) |

## API Changes

### GET /api/status
Now includes new `inputs` field with health status:

```json
{
  "time": 123,
  "counts": {...},
  "queues": {...},
  "signal": {...},
  "emergency": {...},
  "decision": {...},
  "metrics": {...},
  "prediction": {...},
  "mode": "AUTO",
  "manual": {...},
  "inputs": {
    "west_source": "camera",
    "camera_ok": true,
    "last_camera_ts": 1672531200.123,
    "camera_error_count": 0
  },
  "sumo_phase_index": 0,
  "sumo_tls_state": "GrGr",
  "actual_green_group": "NORTH",
  "actual_green_roads": ["north"]
}
```

### WebSocket /ws/live
Same as GET /api/status - includes new `inputs` field.

## Automatic Fallback Mechanism

The HybridProvider includes intelligent error handling:

1. **Per-Read Error Tracking**
   - Counts consecutive camera read failures
   - Falls back to fake data on error
   - Attempts recovery on next read

2. **Persistent Fallback** (After 3 Failures)
   - If camera fails 3 times in a row
   - Disables USE_CAMERA_WEST internally
   - Logs warning
   - Uses fake WEST data for remainder of session

3. **Health Status Reporting**
   - `camera_ok` flag in status shows current state
   - `camera_error_count` shows consecutive failures
   - Dashboard can display camera status to operators

## No Breaking Changes

✅ **Algorithm Logic** - Completely unchanged
- Traffic controller still uses counts for decisions
- Memory learning unchanged
- Emergency preemption unchanged
- Prediction logic unchanged

✅ **SUMO Control** - Completely unchanged
- SUMO still controls all traffic lights
- Phase selection unchanged
- Vehicle simulation unchanged

✅ **Frontend** - Fully backward compatible
- All existing endpoints work unchanged
- New `inputs` field is optional in JSON parsing
- Dashboard UI unaffected (can optionally display camera status)

✅ **Data Schema** - Identical
- Counts always include: car, bike, bus, truck, lorry, auto
- Queue metrics format unchanged
- All per-road metrics unchanged

## Logging

The implementation includes comprehensive logging:

```
INFO:  Hybrid Provider initialized: USE_CAMERA_WEST=false, model_path=backend/models/best.pt, conf=0.30
INFO:  YOLO WEST source initialized: model=backend/models/best.pt, cam=0
DEBUG: Using camera WEST data at t=123
DEBUG: Camera WEST failed, using SUMO data at t=124
WARNING: YOLO read error (attempt 1): [error details]
WARNING: Camera failed 3 times, falling back to fake WEST data
WARNING: Error shutting down YOLO: [error details]
```

## Testing

### Test Camera Integration (without SUMO GUI)
```bash
# Verify hybrid provider works:
python -c "
from controller.data_provider import HybridProvider
provider = HybridProvider(use_camera_west=False)  # Start with fake
counts = provider.get_counts()
health = provider.get_health_status()
print(f'WEST counts: {counts.west}')
print(f'Health: {health}')
"
```

### Test with Camera Enabled
```bash
# Edit .env to enable camera:
# USE_CAMERA_WEST=true

# Then run backend:
python run_with_sumo.py

# Monitor logs for camera status
# Check /api/status for inputs.camera_ok
```

## Files Modified/Created

### Created
- `backend/controller/data_provider.py` - New RoadDataProvider abstraction
- `backend/.env` - Configuration file (default: camera disabled)
- `backend/.env.example` - Example configuration

### Modified
- `backend/app_sumo.py` - Integrated HybridProvider into simulation loop
- `backend/controller/state_models.py` - Added InputHealthInfo model
- `backend/requirements.txt` - Added python-dotenv dependency

### Unchanged
- `backend/controller/yolo_west_source.py` - Used as-is
- `backend/controller/yolo_fake_generator.py` - Used as-is
- `backend/controller/traffic_controller.py` - Unchanged
- `backend/controller/memory_store.py` - Unchanged
- `backend/controller/prediction.py` - Unchanged
- `backend/controller/sumo_connector.py` - Unchanged
- All frontend files - Unchanged

## Future Enhancements

Potential improvements (not implemented in this task):

1. **Persistent Configuration** - Save user's camera preferences
2. **Queue Metrics from Camera** - Compute queue lengths via line crossing
3. **Multi-Camera Support** - Multiple roads from cameras
4. **Model Switching** - Load different YOLO models at runtime
5. **Performance Metrics** - Measure camera FPS vs SUMO cycle time
6. **UI Camera Diagnostics** - Show camera feed in dashboard
