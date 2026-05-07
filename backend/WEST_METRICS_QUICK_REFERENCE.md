# WEST Metrics Configuration Quick Reference

## Minimal Setup (Camera Disabled - Safe Default)
```bash
# .env
USE_CAMERA_WEST=false
WEST_SMOOTHING_ENABLED=true
WEST_SMOOTHING_WINDOW=5
WEST_RESIZE_WIDTH=640
```
**Use Case**: Development, no camera hardware
**Vehicle Source**: YOLO fake generator (existing)
**Result**: Smooth fake metrics

---

## Standard Setup (Real Camera)
```bash
# .env
USE_CAMERA_WEST=true
WEST_CAMERA_INDEX=0
WEST_MODEL_PATH=backend/models/best.pt
WEST_CONF=0.30
WEST_ROI=                           # Full frame
WEST_SMOOTHING_ENABLED=true
WEST_SMOOTHING_WINDOW=5
WEST_RESIZE_WIDTH=640
```
**Use Case**: Real camera, full FOV
**Vehicle Source**: YOLO on camera feed
**Result**: Real vehicle counts with smoothing

---

## ROI-Focused Setup (Lane Detection)
```bash
# .env
USE_CAMERA_WEST=true
WEST_CAMERA_INDEX=0
WEST_MODEL_PATH=backend/models/best.pt
WEST_CONF=0.30
WEST_ROI=100,50,800,450             # Crop to lane area
WEST_SMOOTHING_ENABLED=true
WEST_SMOOTHING_WINDOW=5
WEST_RESIZE_WIDTH=640
```
**Use Case**: Specific traffic lanes only
**Vehicle Source**: YOLO on ROI region
**Result**: Focused metrics, faster processing

---

## High Performance Setup (GPU)
```bash
# .env
USE_CAMERA_WEST=true
WEST_CAMERA_INDEX=0
WEST_MODEL_PATH=backend/models/best_cuda.pt
WEST_CONF=0.30
WEST_ROI=200,100,700,400
WEST_SMOOTHING_ENABLED=true
WEST_SMOOTHING_WINDOW=3             # Smaller window = less latency
WEST_RESIZE_WIDTH=1280              # Higher resolution
```
**Use Case**: Real-time processing, GPU available
**Vehicle Source**: YOLO on full resolution
**Result**: Detailed metrics with minimal latency

---

## Low CPU Setup (Minimal Overhead)
```bash
# .env
USE_CAMERA_WEST=false
WEST_SMOOTHING_ENABLED=false        # Raw counts
WEST_RESIZE_WIDTH=0                 # No resize
```
**Use Case**: Edge device, minimal CPU
**Vehicle Source**: YOLO fake generator
**Result**: No smoothing overhead

---

## Tuning Parameters

### WEST_ROI
| Format | Example | Notes |
|--------|---------|-------|
| Empty | `""` | Full camera frame (default) |
| Coordinates | `100,50,600,400` | Crop to x1,y1,x2,y2 (pixels) |
| Invalid | `abc,def` | Falls back to full frame |

### WEST_SMOOTHING_WINDOW
| Value | Latency | Stability | Use Case |
|-------|---------|-----------|----------|
| 1 | 0 frames | Low | Real-time control |
| 3 | 2 frames | Medium | Balance |
| 5 | 4 frames | High | Stable metrics |
| 10 | 9 frames | Very High | Data logging |

### WEST_RESIZE_WIDTH
| Value | Speed | Quality | Use Case |
|-------|-------|---------|----------|
| 0 | Baseline | Full | Accuracy needed |
| 320 | 3x faster | Lower | Extreme CPU limit |
| 640 | 1.3x faster | Good | Standard |
| 1280 | Slower | Excellent | GPU available |

---

## Checking Configuration

### View Current Settings
```bash
# Check .env is loaded correctly
curl http://localhost:8000/api/status | python -m json.tool | grep -A 5 inputs
```

### Expected Output (Camera Enabled)
```json
{
  "inputs": {
    "west_source": "camera",
    "camera_ok": true,
    "last_camera_ts": 1234567890.5,
    "camera_error_count": 0
  }
}
```

### Expected Output (Camera Disabled/Failed)
```json
{
  "inputs": {
    "west_source": "fake",
    "camera_ok": false,
    "last_camera_ts": null,
    "camera_error_count": 3
  }
}
```

---

## WEST Metrics Fields

| Field | Range | Meaning |
|-------|-------|---------|
| waiting_count | 0-100+ | Total vehicles detected |
| queue_length | 0-100+ | Same as waiting_count |
| cleared_last_interval | 0-50 | Estimated vehicles that left |
| congestion_level | LOW, MEDIUM, HIGH | Traffic intensity |
| congestion_percent | 0-100 | Percentage scale |
| smoothed | true/false | Smoothing applied? |
| roi_active | true/false | ROI cropping active? |

---

## Troubleshooting

### "Camera timeout" errors
**Solution 1**: Disable camera temporarily
```
USE_CAMERA_WEST=false
```
**Solution 2**: Check camera is connected
```bash
python -c "import cv2; cap = cv2.VideoCapture(0); print('OK' if cap.isOpened() else 'FAIL')"
```

### Counts always zero
**Solution**: Check model path
```bash
# Verify file exists
ls -la backend/models/best.pt
```

### High CPU usage
**Solution**: Enable resizing and reduce window
```
WEST_RESIZE_WIDTH=640
WEST_SMOOTHING_WINDOW=3
```

### Counts flickering
**Solution**: Increase smoothing window
```
WEST_SMOOTHING_WINDOW=7
```

### Metrics not updating
**Solution**: Check logs
```bash
tail -f backend/data/logs.jsonl | grep WEST
```

---

## Integration Points

### For Dashboard
Metrics available at:
```
GET /api/status → inputs.west_metrics
```

Response includes all 7 metrics fields for display.

### For Algorithm
Access metrics in simulation loop:
```python
metrics = provider.get_west_metrics()
congestion = metrics['congestion_level']
```

---

**Last Updated**: January 4, 2026
**Version**: 1.0
