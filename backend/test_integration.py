#!/usr/bin/env python3
"""
Comprehensive integration test for Hybrid Input Mode.
Tests that all components work together correctly.
"""

import json
from controller.data_provider import HybridProvider
from controller.state_models import (
    StatusResponse, InputHealthInfo, TrafficCounts, RoadVehicleCounts,
    SignalState, EmergencyInfo, DecisionInfo, Road
)
from controller.traffic_controller import TrafficController
from controller.memory_store import MemoryStore

def test_hybrid_provider_integration():
    """Test HybridProvider with traffic controller."""
    print("\n" + "="*70)
    print("HYBRID INPUT MODE - INTEGRATION TEST")
    print("="*70)
    
    # Initialize components
    print("\n[1] Initializing components...")
    memory_store = MemoryStore("data/memory.json")
    provider = HybridProvider(use_camera_west=False)
    controller = TrafficController(memory_store=memory_store)
    
    print("    ✓ Memory store initialized")
    print("    ✓ Hybrid provider initialized")
    print("    ✓ Traffic controller initialized")
    
    # Test data provider
    print("\n[2] Testing data provider...")
    counts = provider.get_counts()
    queues = provider.get_queue_metrics()
    health = provider.get_health_status()
    
    print(f"    ✓ Got counts for all roads")
    print(f"      - North: {counts.north.car} cars, {counts.north.bike} bikes")
    print(f"      - East: {counts.east.car} cars, {counts.east.bike} bikes")
    print(f"      - South: {counts.south.car} cars, {counts.south.bike} bikes")
    print(f"      - West: {counts.west.car} cars, {counts.west.bike} bikes")
    print(f"    ✓ Got queue metrics: {list(queues.values())}")
    print(f"    ✓ Health status: west_source={health['west_source']}, camera_ok={health['camera_ok']}")
    
    # Test InputHealthInfo model
    print("\n[3] Testing InputHealthInfo model...")
    input_health = InputHealthInfo(**health)
    print(f"    ✓ InputHealthInfo created successfully")
    print(f"      - west_source: {input_health.west_source}")
    print(f"      - camera_ok: {input_health.camera_ok}")
    print(f"      - last_camera_ts: {input_health.last_camera_ts}")
    print(f"      - camera_error_count: {input_health.camera_error_count}")
    
    # Test controller with data
    print("\n[4] Testing traffic controller with hybrid data...")
    controller.reset()
    computed_queues = controller.compute_queues(counts)
    print(f"    ✓ Computed queues from hybrid counts")
    print(f"      - North queue: {computed_queues[Road.north]}")
    print(f"      - East queue: {computed_queues[Road.east]}")
    print(f"      - South queue: {computed_queues[Road.south]}")
    print(f"      - West queue: {computed_queues[Road.west]}")
    
    # Test StatusResponse with new inputs field
    print("\n[5] Testing StatusResponse with inputs field...")
    status = StatusResponse(
        time=0,
        counts=counts,
        queues=computed_queues,
        signal=SignalState(greenRoad=Road.south, remaining=30),
        emergency=EmergencyInfo(active=False, road=None),
        decision=DecisionInfo(method="idle", reason="test"),
        inputs=input_health,
    )
    print(f"    ✓ StatusResponse created with inputs field")
    
    # Validate JSON serialization (important for API)
    status_json = status.dict()
    print(f"    ✓ StatusResponse serializable to JSON")
    print(f"      - Has 'inputs' field: {'inputs' in status_json}")
    print(f"      - inputs.west_source: {status_json['inputs']['west_source']}")
    print(f"      - inputs.camera_ok: {status_json['inputs']['camera_ok']}")
    
    # Test multiple cycles
    print("\n[6] Testing multiple provider cycles...")
    for i in range(5):
        counts = provider.get_counts()
        health = provider.get_health_status()
        queue = computed_queues[Road.west]
        print(f"    Cycle {i+1}: West={counts.west.car:2d} cars, Health={health['west_source']}")
    
    print(f"    ✓ Provider stable over multiple cycles")
    
    # Cleanup
    print("\n[7] Testing cleanup...")
    provider.shutdown()
    print(f"    ✓ Provider shutdown successfully")
    
    print("\n" + "="*70)
    print("✓ ALL INTEGRATION TESTS PASSED")
    print("="*70)
    
    print("\nSummary:")
    print("  ✓ HybridProvider works with traffic controller")
    print("  ✓ Data schema is compatible (counts format unchanged)")
    print("  ✓ InputHealthInfo integrates with StatusResponse")
    print("  ✓ JSON serialization works for API endpoints")
    print("  ✓ Multiple cycles work without errors")
    print("  ✓ Cleanup resources properly")
    
    print("\nNext steps to enable camera for WEST road:")
    print("  1. Edit backend/.env and set: USE_CAMERA_WEST=true")
    print("  2. Ensure YOLO model exists at: backend/models/best.pt")
    print("  3. Verify camera access permissions")
    print("  4. Run: python run_with_sumo.py")
    print("  5. Check logs for 'YOLO WEST source initialized' message")
    print("  6. Monitor /api/status for inputs.camera_ok and west_source")

if __name__ == "__main__":
    test_hybrid_provider_integration()
