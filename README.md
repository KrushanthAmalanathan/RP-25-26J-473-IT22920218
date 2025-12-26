# Smart Traffic Control with SUMO Integration

Complete smart traffic control system with memory-based adaptive signaling and SUMO visualization.

## Features
- ✅ Memory-based adaptive traffic light control
- ✅ Real-time SUMO traffic simulation with GUI
- ✅ Emergency vehicle preemption (< 5 seconds)
- ✅ Live dashboard with charts and junction view
- ✅ WebSocket streaming for real-time updates
- ✅ Weighted queue scoring (bus/truck > car > bike)

## Prerequisites

### 1. Install SUMO
**Windows:**
- Download from: https://www.eclipse.org/sumo/
- Install to default location (e.g., `C:\Program Files (x86)\Eclipse\Sumo`)
- Add SUMO bin to PATH:
  ```powershell
  $env:PATH += ";C:\Program Files (x86)\Eclipse\Sumo\bin"
  ```

**Linux/Mac:**
```bash
sudo apt-get install sumo sumo-tools sumo-doc  # Ubuntu/Debian
brew install sumo  # macOS
```

### 2. Python 3.9+
Already configured in backend venv.

### 3. Node.js 16+
For frontend React app.

## Setup

### Backend Setup

```powershell
cd backend

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Install SUMO Python libraries
pip install traci sumolib

# Verify SUMO installation
python -c "import traci; print('TraCI OK')"
```

### SUMO Network Setup

```powershell
cd ..\sumo

# Build network from node/edge files
.\build_network.ps1

# This creates junction.net.xml needed for simulation
```

### Frontend Setup

```powershell
cd ..\frontend

# Already done, but if needed:
npm install
```

## Running the System

### Option 1: With SUMO GUI (Recommended for visualization)

**Terminal 1 - Backend:**
```powershell
cd backend
.\venv\Scripts\Activate.ps1
python run_with_sumo.py
```

**Terminal 2 - Frontend:**
```powershell
cd frontend
npm run dev
```

**Then:**
1. Open browser: http://localhost:5173
2. Click "Start" button in dashboard
3. Watch SUMO GUI show traffic + see live dashboard updates

### Option 2: Headless SUMO (Faster, no GUI)

Edit `backend/run_with_sumo.py`:
```python
sumo_connector = SUMOConnector("../sumo/junction.sumocfg", use_gui=False)
```

### Option 3: Original Fake Data (No SUMO)

```powershell
cd backend
.\venv\Scripts\Activate.ps1
uvicorn app:app --port 8000
```

Then use the original endpoints.

## Architecture

```
┌─────────────┐         TraCI          ┌──────────────┐
│    SUMO     │ ◄──────────────────────► │   Backend    │
│ Simulation  │   Vehicle counts        │   FastAPI    │
│   + GUI     │   TL phase control      │ + Controller │
└─────────────┘                         └───────┬──────┘
                                                │
                                         WebSocket/REST
                                                │
                                        ┌───────▼──────┐
                                        │   Frontend   │
                                        │ React + Vite │
                                        └──────────────┘
```

## How It Works

1. **SUMO generates realistic traffic** based on flows defined in `junction.rou.xml`
2. **Backend reads vehicle counts** per road every second via TraCI
3. **Adaptive controller decides** best green phase using memory-based learning
4. **Backend sends phase commands** back to SUMO to control traffic lights
5. **Frontend displays** live counts, queues, signal status, and charts
6. **Emergency vehicles** (e.g., ID contains "ambulance") trigger preemption

## Key Files

**Backend:**
- `controller/sumo_connector.py` - TraCI interface
- `controller/traffic_controller.py` - Adaptive algorithm
- `controller/memory_store.py` - Learning memory
- `app_sumo.py` - FastAPI with SUMO integration

**SUMO:**
- `junction.net.xml` - Network topology
- `junction.rou.xml` - Vehicle routes and flows
- `junction.sumocfg` - Simulation config

**Frontend:**
- `src/pages/Dashboard.jsx` - Main UI
- `src/components/` - Road cards, charts, etc.

## Emergency Vehicle Test

At t=90s, an ambulance enters from the south road. The system should:
1. Detect the emergency vehicle
2. Switch to south green within 5 seconds
3. Display red emergency banner in dashboard

## Troubleshooting

**"SUMO not found":**
- Verify SUMO is in PATH: `where sumo` (Windows) or `which sumo` (Linux/Mac)
- Reinstall and add to PATH

**"TraCI connection failed":**
- Make sure no other SUMO instance is running
- Check `junction.net.xml` exists (run `build_network.ps1`)

**Frontend shows "Loading...":**
- Ensure backend is running on port 8000
- Check browser console for WebSocket errors
- Try POST to http://localhost:8000/api/control/start

## API Endpoints

- `GET /api/status` - Current traffic state
- `GET /api/memory/summary` - Learning statistics
- `POST /api/control/start` - Start simulation
- `POST /api/control/stop` - Stop simulation
- `WS /ws/live` - Live updates stream

## Configuration

**Adjust traffic flow intensity:**
Edit `sumo/junction.rou.xml` - change `probability` values in `<flow>` tags.

**Change decision cycle:**
Edit `backend/controller/traffic_controller.py`:
```python
self.decision_cycle = 5  # seconds between decisions
```

**Modify vehicle weights:**
Edit `backend/controller/traffic_controller.py`:
```python
self.weights = {"bike": 1, "car": 2, "auto": 2, "bus": 4, "truck": 4, "lorry": 4}
```
