#!/usr/bin/env python3
"""
Quick launcher for Smart Traffic with SUMO integration.
Run this instead of uvicorn when you want to use SUMO visualization.
"""

import uvicorn
import sys

if __name__ == "__main__":
    print("=" * 60)
    print("Smart Traffic Control System with SUMO")
    print("=" * 60)
    print("Starting FastAPI server with SUMO integration...")
    print()
    print("1. Backend will start on: http://localhost:8000")
    print("2. Click 'Start' in frontend dashboard to launch SUMO")
    print("3. SUMO GUI will open showing the junction")
    print()
    print("Make sure:")
    print("  - SUMO is installed and in PATH")
    print("  - junction.net.xml exists in ../sumo/")
    print("  - Frontend is running on http://localhost:5173")
    print("=" * 60)
    print()
    
    try:
        uvicorn.run("app_sumo:app", host="0.0.0.0", port=8000, reload=False)
    except KeyboardInterrupt:
        print("\nShutting down...")
        sys.exit(0)
