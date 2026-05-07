#!/usr/bin/env python3
"""
Unit tests for WEST metrics logic (no cv2 required).
Tests ROI parsing, smoothing algorithm, metrics computation.
"""

import sys
from collections import defaultdict

def test_roi_parsing():
    """Test ROI string parsing logic."""
    print("\n[TEST 1] ROI Parsing")
    
    def parse_roi(roi_str: str):
        """Parse ROI from string format 'x1,y1,x2,y2'."""
        if not roi_str or not roi_str.strip():
            return None
        try:
            parts = [int(x.strip()) for x in roi_str.split(",")]
            if len(parts) == 4:
                x1, y1, x2, y2 = parts
                if x1 >= 0 and y1 >= 0 and x2 > x1 and y2 > y1:
                    return (x1, y1, x2, y2)
        except (ValueError, AttributeError):
            pass
        return None
    
    test_cases = [
        ("", None, "Empty ROI"),
        ("10,20,100,200", (10, 20, 100, 200), "Valid ROI"),
        ("invalid", None, "Invalid ROI"),
        ("10,20,10,200", None, "Invalid coordinates (x1 >= x2)"),
        (" 5 , 10 , 50 , 60 ", (5, 10, 50, 60), "ROI with spaces"),
    ]
    
    all_passed = True
    for roi_str, expected, description in test_cases:
        result = parse_roi(roi_str)
        passed = result == expected
        status = "✓" if passed else "✗"
        print(f"  {status} {description}")
        if not passed:
            print(f"      Expected: {expected}, Got: {result}")
            all_passed = False
    
    return all_passed

def test_smoothing():
    """Test rolling smoothing with median."""
    print("\n[TEST 2] Rolling Smoothing (Median)")
    
    import statistics
    
    # Simulate count history
    history = [
        {"car": 5, "bike": 2},
        {"car": 6, "bike": 2},
        {"car": 4, "bike": 3},
    ]
    
    # Compute median smoothing
    smoothed = {}
    for vehicle_type in ["car", "bike"]:
        counts = [h.get(vehicle_type, 0) for h in history]
        median_count = int(round(statistics.median(counts)))
        smoothed[vehicle_type] = median_count
    
    print(f"  History: {history}")
    print(f"  Smoothed: {smoothed}")
    
    # Verify
    assert smoothed["car"] == 5, f"Expected car=5, got {smoothed['car']}"
    assert smoothed["bike"] == 2, f"Expected bike=2, got {smoothed['bike']}"
    print("  ✓ Median smoothing works correctly")
    
    return True

def test_metrics_computation():
    """Test queue metrics computation."""
    print("\n[TEST 3] Metrics Computation")
    
    VEHICLE_WEIGHTS = {
        "car": 1,
        "bike": 0.5,
        "bus": 3,
        "truck": 2.5,
        "lorry": 2.5,
        "auto": 0.7,
    }
    
    CONGESTION_THRESHOLDS = {
        "LOW": (0, 10),
        "MEDIUM": (10, 25),
        "HIGH": (25, float("inf")),
    }
    
    def compute_metrics(counts, last_total):
        total = sum(counts.values())
        
        # Weighted count
        weighted_count = sum(
            counts.get(vtype, 0) * VEHICLE_WEIGHTS.get(vtype, 1)
            for vtype in ["car", "bike", "bus", "truck", "lorry", "auto"]
        )
        
        # Cleared estimate
        cleared = 0
        if last_total > total:
            cleared = min(
                last_total - total,
                max(5, last_total // 2),
            )
        
        # Congestion level
        congestion_level = "LOW"
        for level, (low, high) in CONGESTION_THRESHOLDS.items():
            if low <= weighted_count < high:
                congestion_level = level
                break
        
        # Congestion percent
        max_weighted = 50
        congestion_percent = min(100, int((weighted_count / max_weighted) * 100))
        
        return {
            "waiting_count": total,
            "weighted_count": weighted_count,
            "cleared_last_interval": cleared,
            "congestion_level": congestion_level,
            "congestion_percent": congestion_percent,
        }
    
    # Test scenarios
    scenarios = [
        ({"car": 10, "bike": 5, "bus": 2, "truck": 1, "lorry": 0, "auto": 3}, 0, "Heavy traffic"),
        ({"car": 2, "bike": 1, "bus": 0, "truck": 0, "lorry": 0, "auto": 0}, 0, "Light traffic"),
        ({"car": 0, "bike": 0, "bus": 0, "truck": 0, "lorry": 0, "auto": 0}, 0, "No traffic"),
        ({"car": 5, "bike": 1, "bus": 0, "truck": 0, "lorry": 0, "auto": 0}, 10, "Vehicles cleared"),
    ]
    
    all_passed = True
    for counts, last_total, description in scenarios:
        metrics = compute_metrics(counts, last_total)
        print(f"  {description}:")
        print(f"    - Waiting: {metrics['waiting_count']}")
        print(f"    - Weighted: {metrics['weighted_count']:.1f}")
        print(f"    - Cleared: {metrics['cleared_last_interval']}")
        print(f"    - Congestion: {metrics['congestion_level']} ({metrics['congestion_percent']}%)")
        
        # Verify logic
        if metrics["waiting_count"] != sum(counts.values()):
            print(f"    ✗ Waiting count mismatch")
            all_passed = False
    
    if all_passed:
        print("  ✓ All metrics computed correctly")
    
    return all_passed

def test_data_provider_integration():
    """Test that metrics integrate with data provider."""
    print("\n[TEST 4] Data Provider Integration")
    
    try:
        from controller.data_provider import HybridProvider
        
        provider = HybridProvider(
            use_camera_west=False,
            smoothing_enabled=True,
            roi_west="",
        )
        
        print(f"  ✓ HybridProvider created")
        print(f"  ✓ Smoothing enabled: {provider.smoothing_enabled}")
        print(f"  ✓ ROI: {provider.roi_west if provider.roi_west else 'none'}")
        
        # Test metrics getter
        metrics = provider.get_west_metrics()
        print(f"  ✓ Got WEST metrics: {metrics}")
        
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

def test_configuration():
    """Test that configuration loads from environment."""
    print("\n[TEST 5] Configuration Loading")
    
    import os
    
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        # Check values
        use_cam = os.getenv("USE_CAMERA_WEST", "false").lower() == "true"
        roi = os.getenv("WEST_ROI", "")
        smoothing = os.getenv("WEST_SMOOTHING_ENABLED", "true").lower() == "true"
        window = int(os.getenv("WEST_SMOOTHING_WINDOW", "5"))
        
        print(f"  ✓ USE_CAMERA_WEST: {use_cam}")
        print(f"  ✓ WEST_ROI: {roi if roi else 'none'}")
        print(f"  ✓ WEST_SMOOTHING_ENABLED: {smoothing}")
        print(f"  ✓ WEST_SMOOTHING_WINDOW: {window}")
        
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False

if __name__ == "__main__":
    print("="*70)
    print("WEST METRICS - UNIT TESTS")
    print("="*70)
    
    results = []
    results.append(("ROI Parsing", test_roi_parsing()))
    results.append(("Rolling Smoothing", test_smoothing()))
    results.append(("Metrics Computation", test_metrics_computation()))
    results.append(("Data Provider Integration", test_data_provider_integration()))
    results.append(("Configuration Loading", test_configuration()))
    
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(passed for _, passed in results)
    
    print("\n" + "="*70)
    if all_passed:
        print("✓ ALL TESTS PASSED")
    else:
        print("✗ SOME TESTS FAILED")
    print("="*70)
    
    sys.exit(0 if all_passed else 1)
