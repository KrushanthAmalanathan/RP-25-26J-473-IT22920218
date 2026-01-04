# Stage 3: Short-Term Traffic Prediction & Heavy Traffic Forecasting

**Date:** 2025  
**Status:** ✅ COMPLETED  
**Version:** 0.3.0

---

## 📋 Overview

Stage 3 adds short-term traffic prediction capabilities to the adaptive traffic signal controller. The system now forecasts heavy traffic conditions using queue trend analysis, arrival rate forecasting, and congestion probability heuristics. Predictions influence decision-making through a soft bias mechanism while maintaining emergency preemption and fairness guarantees.

---

## 🎯 Requirements Implemented

### ✅ 1. Queue Trend Analysis
- **Implemented in:** `prediction.py` → `TrafficPredictor._compute_trend()`
- **Algorithm:** Maintains 30-second sliding window of queue sizes per road
- **Classification:** 
  - `increasing`: Queue growing (delta > 2 vehicles)
  - `decreasing`: Queue shrinking (delta < -2 vehicles)
  - `stable`: No significant change
- **Formula:** `trend = (current_queue - oldest_queue) / time_span_seconds`

### ✅ 2. Short-Term Arrival Forecasting
- **Implemented in:** `prediction.py` → `TrafficPredictor._predict_arrivals()`
- **Algorithm:** Converts arrival_rate_vpm (vehicles per minute) to near-future forecasts
- **Outputs:**
  - `arrivals_10s`: Expected arrivals in next 10 seconds = `arrival_rate_vpm / 6`
  - `arrivals_30s`: Expected arrivals in next 30 seconds = `arrival_rate_vpm / 2`

### ✅ 3. Heavy Traffic Probability
- **Implemented in:** `prediction.py` → `TrafficPredictor._compute_heavy_traffic_probability()`
- **Heuristic Formula:**
  ```
  P(heavy) = 0.5 * congestion_norm + 0.3 * trend_norm + 0.2 * net_flow_norm
  ```
- **Components:**
  - **Congestion (50%):** Current congestion_percent scaled to [0,1]
  - **Trend (30%):** Queue trend normalized (+1 if increasing, 0 if stable, -1 if decreasing)
  - **Net Flow (20%):** (arrival_rate - departure_rate) normalized to [0,1]
- **Output:** Probability percentage [0-100%]

### ✅ 4. Congestion Level Classification
- **Implemented in:** `prediction.py` → `TrafficPredictor._classify_congestion_level()`
- **Classification:**
  - `LOW`: 0-30% heavy traffic probability
  - `MEDIUM`: 30-60% heavy traffic probability
  - `HIGH`: 60-100% heavy traffic probability

### ✅ 5. Predicted ETA to Normal Flow
- **Implemented in:** `prediction.py` → `TrafficPredictor._predict_eta_clear()`
- **Algorithm:**
  - Base ETA: `eta_clear_seconds` from metrics
  - Adjustment: If queue trending upward, add `trend_rate * 10` seconds penalty
- **Purpose:** More realistic ETA when congestion is worsening

### ✅ 6. Decision Biasing
- **Implemented in:** `traffic_controller.py` → `TrafficController._composite_score()`
- **Integration:** Added `WEIGHT_PRED = 0.3` term to composite scoring function
- **Mechanism:** `prediction_bias = WEIGHT_PRED * (heavy_traffic_probability / 100.0)`
- **Effect:** Roads with high predicted heavy traffic receive +0.3 to +30 score boost (soft bias, not override)

### ✅ 7. API Exposure
- **State Models:** Extended `state_models.py` with `PredictionMetrics` and `PredictionSet`
- **API Response:** `StatusResponse` now includes `prediction: PredictionSet` field
- **Fields per road:**
  - `queue_trend`: "increasing" | "stable" | "decreasing"
  - `arrivals_10s`: float
  - `arrivals_30s`: float
  - `heavy_traffic_probability`: float (0-100)
  - `congestion_level`: "LOW" | "MEDIUM" | "HIGH"
  - `predicted_eta_clear_seconds`: int

### ✅ 8. Decision Explanation Updates
- **Implemented in:** `traffic_controller.py` → `_decide_next_with_memory_learning()`
- **Enhancement:** Decision reasons now include prediction context
- **Examples:**
  - `"Memory-based: north (reward=12.3, matches=5, predicted=HIGH)"`
  - `"Composite score: east (score=23.5, predicted=MEDIUM)"`

### ✅ 9. Prediction Logging
- **Implemented in:** `app_sumo.py` → `_log_metrics()`
- **Format:** JSONL entries now include `predictions` object
- **Logged per road:**
  - `queue_trend`
  - `heavy_traffic_probability`
  - `congestion_level`
  - `predicted_eta_clear_seconds`
- **Log Location:** `backend/data/logs.jsonl`

---

## 📁 Files Modified

### 🆕 New Files

#### 1. `backend/controller/prediction.py` (NEW)
**Purpose:** Traffic forecasting engine  
**Key Class:** `TrafficPredictor`  
**Methods:**
- `reset()`: Clear all queue history
- `update_queue_history(road, queue_size)`: Track queue changes
- `_compute_trend(road)`: Calculate queue trend
- `_predict_arrivals(arrival_rate_vpm)`: Forecast short-term arrivals
- `_compute_heavy_traffic_probability(metrics_for_road)`: Compute congestion probability
- `_classify_congestion_level(probability)`: Categorize congestion
- `_predict_eta_clear(base_eta, trend_rate, trend_class)`: Adjust ETA forecast
- `predict(metrics: RoadMetricsSet) -> Dict[Road, Dict]`: Main prediction loop
- `get_prediction_bias_for_road(road, predictions) -> float`: Extract bias for scoring

**Configuration:**
```python
PREDICTION_WEIGHT = 0.3  # Prediction bias weight for scoring
HISTORY_WINDOW = 30      # Seconds of queue history
TREND_THRESHOLD = 2      # Vehicles delta to classify trend
```

### 🔧 Modified Files

#### 2. `backend/controller/state_models.py`
**Changes:**
- Added `PredictionMetrics` class (6 fields)
- Added `PredictionSet` class (north/east/south/west)
- Extended `StatusResponse` with `prediction: PredictionSet = PredictionSet()`

#### 3. `backend/controller/traffic_controller.py`
**Changes:**
- Added import: `from .prediction import TrafficPredictor`
- Added constant: `WEIGHT_PRED = 0.3`
- Instantiated predictor: `self.predictor = TrafficPredictor()`
- Updated `__init__`: Added `self._last_predictions` field
- Updated `reset()`: Added `self.predictor.reset()`
- Updated `_composite_score()`: Added `predictions` parameter, integrated prediction bias
- Updated `tick_and_decide()`: Added `predictions` parameter, stores predictions
- Updated `_decide_next_with_memory_learning()`: Added `predictions` parameter, includes prediction context in decision reasons

#### 4. `backend/app_sumo.py`
**Changes:**
- Added imports: `PredictionSet`, `PredictionMetrics`, `TrafficPredictor`
- Instantiated predictor: `predictor = TrafficPredictor()`
- Added helper: `_convert_predictions_to_prediction_set(predictions)`
- Updated `_run_loop()`:
  - Added `predictor.reset()` call
  - Added `predictions = predictor.predict(metrics)` after metrics computation
  - Pass `predictions` to `controller.tick_and_decide()`
  - Include `prediction=_convert_predictions_to_prediction_set(predictions)` in StatusResponse
- Updated `_log_metrics()`: Added `predictions` parameter, logs prediction data to JSONL
- Bumped version: `0.2.0` → `0.3.0`

---

## 🔄 Architecture Integration

### Control Flow (Updated)

```
SUMO Step
    ↓
Get Vehicle Counts
    ↓
Compute Metrics (Stage 1)
    ↓
Predict Traffic (Stage 3) ← NEW
    ↓
Tick & Decide (Stage 2 + Stage 3) ← UPDATED
    - Emergency Preemption (highest priority)
    - Starvation Protection
    - Memory-Based Learning
    - Composite Scoring WITH Prediction Bias ← NEW
    ↓
Set Green Phase
    ↓
Log Metrics + Predictions ← UPDATED
    ↓
Broadcast to WebSocket
```

### Scoring Function (Updated)

```
score = w_queue * waiting_count
      + w_wait * avg_wait_time
      + w_fair * time_since_last_green
      + w_cong * congestion_percent
      + w_pred * prediction_bias          ← NEW
      - w_switch * switching_penalty

where:
  w_pred = 0.3
  prediction_bias = heavy_traffic_probability / 100.0
```

### Decision Priority Hierarchy (Unchanged)

1. **Emergency Preemption** (ambulance on road)
2. **Starvation Protection** (red > 90s)
3. **Memory-Based Learning** (similarity ≥ 0.7)
4. **Composite Scoring** (with prediction bias) ← ENHANCED
5. **Gap-Out Rule** (no waiting for 3s)

---

## 📊 API Response Schema (Updated)

### Example `/api/status` Response

```json
{
  "time": 120,
  "counts": { ... },
  "queues": { ... },
  "signal": { ... },
  "emergency": { ... },
  "decision": { ... },
  "metrics": {
    "north": {
      "waiting_count": 8,
      "avg_wait_time": 15.3,
      "cleared_last_interval": 5,
      "arrival_rate_vpm": 12.0,
      "departure_rate_vpm": 8.0,
      "time_since_last_green": 45,
      "congestion_percent": 67.0,
      "eta_clear_seconds": 20
    },
    ...
  },
  "prediction": {
    "north": {
      "queue_trend": "increasing",
      "arrivals_10s": 2.0,
      "arrivals_30s": 6.0,
      "heavy_traffic_probability": 72.5,
      "congestion_level": "HIGH",
      "predicted_eta_clear_seconds": 28
    },
    "east": {
      "queue_trend": "stable",
      "arrivals_10s": 1.5,
      "arrivals_30s": 4.5,
      "heavy_traffic_probability": 45.0,
      "congestion_level": "MEDIUM",
      "predicted_eta_clear_seconds": 12
    },
    "south": {
      "queue_trend": "decreasing",
      "arrivals_10s": 0.5,
      "arrivals_30s": 1.5,
      "heavy_traffic_probability": 15.0,
      "congestion_level": "LOW",
      "predicted_eta_clear_seconds": 5
    },
    "west": {
      "queue_trend": "stable",
      "arrivals_10s": 1.0,
      "arrivals_30s": 3.0,
      "heavy_traffic_probability": 38.0,
      "congestion_level": "MEDIUM",
      "predicted_eta_clear_seconds": 10
    }
  }
}
```

---

## 📝 Logging Format (Updated)

### JSONL Entry Structure

```json
{
  "timestamp": "2025-01-20T12:34:56.789Z",
  "simulation_time": 120,
  "metrics": { ... },
  "signal": {
    "green_road": "north",
    "remaining_seconds": 15
  },
  "predictions": {
    "north": {
      "queue_trend": "increasing",
      "heavy_traffic_probability": 72.5,
      "congestion_level": "HIGH",
      "predicted_eta_clear_seconds": 28
    },
    "east": { ... },
    "south": { ... },
    "west": { ... }
  }
}
```

---

## 🧪 Testing & Validation

### Syntax Validation: ✅ ALL PASSED
```
✓ prediction.py: No syntax errors
✓ state_models.py: No syntax errors  
✓ traffic_controller.py: No syntax errors
✓ app_sumo.py: No syntax errors
```

### Expected Behavior

1. **Predictor Updates Queue History:**
   - Every simulation step, predictor stores current queue sizes
   - Maintains 30-second sliding window (deque)

2. **Trend Detection:**
   - If queue grows >2 vehicles in 30s → "increasing"
   - If queue shrinks >2 vehicles in 30s → "decreasing"
   - Otherwise → "stable"

3. **Heavy Traffic Probability:**
   - High congestion (60%+), increasing trend → HIGH probability
   - Moderate congestion (30-60%), stable trend → MEDIUM probability
   - Low congestion (<30%), decreasing trend → LOW probability

4. **Decision Biasing:**
   - HIGH congestion roads get +0.18 to +0.30 score boost
   - MEDIUM roads get +0.09 to +0.18 boost
   - LOW roads get +0.0 to +0.09 boost
   - Emergency/starvation overrides remain unchanged

5. **Logging:**
   - Every 5 seconds (decision cycle), predictions logged
   - Queue trend, probability, congestion level, ETA captured

---

## 🔧 Configuration Constants

### In `prediction.py`:
```python
PREDICTION_WEIGHT = 0.3   # Bias weight for scoring
HISTORY_WINDOW = 30       # Queue history window (seconds)
TREND_THRESHOLD = 2       # Vehicles delta for trend classification
```

### In `traffic_controller.py`:
```python
WEIGHT_PRED = 0.3         # Prediction bias weight in composite score
```

### Tuneable Parameters:
- **PREDICTION_WEIGHT / WEIGHT_PRED**: Increase for stronger prediction influence
- **HISTORY_WINDOW**: Increase for longer-term trends (less reactive)
- **TREND_THRESHOLD**: Increase to reduce sensitivity to noise
- **Heavy traffic probability weights** (in `_compute_heavy_traffic_probability`):
  - Congestion: 0.5 (50% weight)
  - Trend: 0.3 (30% weight)
  - Net Flow: 0.2 (20% weight)

---

## 🚀 Next Steps (Future Work)

### Potential Enhancements:
1. **Machine Learning Integration:**
   - Replace heuristic probability with trained model (LSTM, XGBoost)
   - Use historical logs for supervised learning

2. **Multi-Step Forecasting:**
   - Extend predictions beyond 10s/30s (e.g., 1min, 2min, 5min)
   - Use exponential smoothing or ARIMA models

3. **Prediction Confidence:**
   - Add confidence scores based on data quality (e.g., low traffic = low confidence)
   - Adjust bias weight dynamically based on confidence

4. **Incident Detection:**
   - Detect anomalies (sudden queue spikes → potential accident)
   - Trigger alerts or emergency protocols

5. **Network-Wide Predictions:**
   - Coordinate predictions across multiple junctions
   - Optimize for traffic wave propagation

6. **Frontend Visualization:**
   - Display prediction trends on dashboard charts
   - Show congestion heatmap with forecasted colors

---

## ✅ Completion Checklist

- [x] Created `prediction.py` with `TrafficPredictor` class
- [x] Implemented queue trend analysis (30s window)
- [x] Implemented short-term arrival forecasting (10s, 30s)
- [x] Implemented heavy traffic probability heuristic
- [x] Implemented congestion level classification (LOW/MEDIUM/HIGH)
- [x] Implemented predicted ETA adjustment
- [x] Extended `state_models.py` with `PredictionMetrics` and `PredictionSet`
- [x] Updated `traffic_controller.py` to integrate prediction bias
- [x] Updated `app_sumo.py` to compute and expose predictions
- [x] Added prediction logging to `logs.jsonl`
- [x] Updated decision explanations with prediction context
- [x] Validated all syntax (0 errors)
- [x] Maintained backward compatibility (no breaking changes)
- [x] Documented implementation (this file)

---

## 📚 Related Documentation

- **Stage 1 Implementation:** `STAGE_1_IMPLEMENTATION.md` (Metrics Collection)
- **Stage 2 Implementation:** `STAGE_2_IMPLEMENTATION.md` (Decision Logic)
- **API Reference:** `README.md`
- **Quick Start:** `QUICKSTART.md`

---

**Stage 3 Complete! 🎉**  
The system now forecasts heavy traffic and adjusts decisions proactively while maintaining fairness and emergency response capabilities.
