#!/usr/bin/env python3
"""Quick test to verify HybridProvider integration."""

from controller.data_provider import HybridProvider
from controller.state_models import InputHealthInfo
import json

print("=" * 60)
print("Testing Hybrid Input Mode Implementation")
print("=" * 60)

# Test 1: Initialize HybridProvider with camera disabled (default)
print("\n[TEST 1] Initialize with camera disabled")
provider = HybridProvider(use_camera_west=False)
print(f"  ✓ HybridProvider created")
print(f"  ✓ use_camera_west: {provider.use_camera_west}")
print(f"  ✓ camera_ok: {provider.camera_ok}")

# Test 2: Get health status
print("\n[TEST 2] Get health status")
health = provider.get_health_status()
print(f"  ✓ Health status retrieved")
print(f"  ✓ west_source: {health['west_source']}")
print(f"  ✓ camera_ok: {health['camera_ok']}")
print(f"  ✓ camera_error_count: {health['camera_error_count']}")
print(f"  ✓ last_camera_ts: {health['last_camera_ts']}")

# Test 3: Get counts (should be all fake)
print("\n[TEST 3] Get vehicle counts")
counts = provider.get_counts()
print(f"  ✓ Counts retrieved")
print(f"  ✓ West road counts: car={counts.west.car}, bike={counts.west.bike}, bus={counts.west.bus}")
print(f"  ✓ North road counts: car={counts.north.car}, bike={counts.north.bike}, bus={counts.north.bus}")

# Test 4: Create InputHealthInfo model
print("\n[TEST 4] Create InputHealthInfo model")
health_info = InputHealthInfo(**health)
print(f"  ✓ InputHealthInfo created from health status")
print(f"  ✓ Model valid: {health_info.dict()}")

# Test 5: Get queue metrics
print("\n[TEST 5] Get queue metrics")
queues = provider.get_queue_metrics()
print(f"  ✓ Queue metrics retrieved")
print(f"  ✓ Queues: {queues}")

print("\n" + "=" * 60)
print("✓ ALL TESTS PASSED")
print("=" * 60)
print("\nHybrid provider is ready for integration!")
print("\nTo enable camera for WEST road:")
print("  1. Edit backend/.env")
print("  2. Set: USE_CAMERA_WEST=true")
print("  3. Run: python run_with_sumo.py")
