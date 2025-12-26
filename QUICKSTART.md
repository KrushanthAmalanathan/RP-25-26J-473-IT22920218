# Quick Start Guide - SUMO Integration

## What You Have Now

✅ **Backend** - FastAPI with memory-based adaptive control
✅ **Frontend** - React dashboard with live charts  
✅ **SUMO Integration** - Real traffic simulation with GUI visualization
✅ **TraCI Connector** - Reads vehicle data, controls traffic lights

## Installation Steps

### 1. Install SUMO (Required)

**Windows:**
1. Download: https://sumo.dlr.de/docs/Downloads.php
2. Install to: `C:\Program Files (x86)\Eclipse\Sumo`
3. Add to PATH:
   ```powershell
   [Environment]::SetEnvironmentVariable("PATH", $env:PATH + ";C:\Program Files (x86)\Eclipse\Sumo\bin", "User")
   ```
4. Restart terminal and verify:
   ```powershell
   netconvert --version
   ```

### 2. Build SUMO Network

```powershell
cd C:\Users\thund\Desktop\smart-traffic\sumo
.\build_network.ps1
```

This creates `junction.net.xml` from the node/edge definitions.

### 3. Run the System

**Terminal 1 - Backend with SUMO:**
```powershell
cd C:\Users\thund\Desktop\smart-traffic\backend
.\venv\Scripts\Activate.ps1
python run_with_sumo.py
```

**Terminal 2 - Frontend (already running):**
Your frontend is already at http://localhost:5173

**Then:**
1. Open browser: http://localhost:5173
2. Click **"Start"** button
3. **SUMO GUI will launch** showing the 4-way junction
4. Watch real vehicles move through the junction
5. Dashboard shows live counts, queues, and adaptive decisions

## What You'll See

### SUMO GUI Window:
- 4-way junction with traffic lights
- Cars, bikes, buses, trucks moving realistically
- Traffic lights changing based on your adaptive algorithm
- At t=90s: Red ambulance (emergency vehicle)

### Dashboard:
- **4 Road Cards** - Live vehicle counts by type
- **Signal Status** - Current green road + countdown
- **Junction View** - Visual overview with color coding
- **Charts** - Queue trends over time
- **Emergency Banner** - Appears when ambulance detected

## How It Works

```
1. SUMO simulates traffic → generates vehicles on 4 roads
2. TraCI reads vehicle counts → sent to backend controller
3. Controller decides optimal phase → using memory-based learning
4. Backend sends phase command → SUMO changes traffic lights
5. Dashboard updates → via WebSocket stream (every 1 second)
```

## Key Features Demonstrated

✅ **Adaptive Control** - Learns from past decisions (memory-based)
✅ **Queue Optimization** - Weighted by vehicle type (bus > car > bike)
✅ **Emergency Preemption** - Ambulance gets green within 5 seconds
✅ **Real-Time Visualization** - Both SUMO and web dashboard
✅ **Data Logging** - All decisions stored in memory.json

## Alternative: Without SUMO (Fake Data)

If SUMO isn't installed, use the original mode:

```powershell
cd backend
.\venv\Scripts\Activate.ps1
uvicorn app:app --port 8000
```

This uses synthetic vehicle counts (no SUMO GUI).

## Troubleshooting

**"netconvert not found":**
- SUMO not installed or not in PATH
- Restart terminal after adding to PATH

**"TraCI connection failed":**
- Run `build_network.ps1` first
- Check `junction.net.xml` exists in sumo/ folder

**Dashboard shows "Loading...":**
- Backend not running (check Terminal 1)
- Try: `Invoke-WebRequest http://localhost:8000/api/status`

**No vehicles in SUMO:**
- Routes are defined in `junction.rou.xml`
- Traffic starts light, increases over time

## Files Created

**SUMO Configuration:**
- `sumo/junction.nod.xml` - Junction nodes
- `sumo/junction.edg.xml` - Road edges  
- `sumo/junction.rou.xml` - Vehicle routes & flows
- `sumo/junction.sumocfg` - Simulation config
- `sumo/junction.net.xml` - Compiled network (created by build script)

**Backend:**
- `backend/controller/sumo_connector.py` - TraCI interface
- `backend/app_sumo.py` - FastAPI with SUMO
- `backend/run_with_sumo.py` - Quick launcher

**Documentation:**
- `README.md` - Complete system documentation
- `QUICKSTART.md` - This file

## Next Steps

1. **Adjust traffic flow:** Edit `sumo/junction.rou.xml` probability values
2. **Change decision logic:** Modify `backend/controller/traffic_controller.py`
3. **Tweak vehicle weights:** Update weights dict in controller
4. **Add more roads:** Extend SUMO network files
5. **Export data:** Memory records saved in `backend/data/memory.json`

## Demo Scenario

Watch for the emergency vehicle:
- At **t=90 seconds**, red ambulance enters from **south**
- System detects emergency
- Traffic light switches to **south green within 5 seconds**
- Dashboard shows **red emergency banner**
- After ambulance passes, returns to adaptive control

Enjoy your smart traffic system! 🚦
