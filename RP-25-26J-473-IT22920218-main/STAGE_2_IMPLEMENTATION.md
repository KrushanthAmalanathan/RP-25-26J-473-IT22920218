# STAGE 2: Decision Logic & Memory-Based Learning Improvement - COMPLETE

## Summary
Successfully implemented advanced decision logic with composite scoring, memory-based learning, dynamic green duration, fairness guarantees, and comprehensive decision explanations.

## Key Improvements

### 1. Composite Scoring Function
**Location:** `traffic_controller.py` - `_composite_score()` method

Replaced simple queue-based selection with multi-factor scoring:

```
score(road) = 
    1.0  * waiting_count           (penalize roads with many vehicles)
  + 0.8  * avg_waiting_time        (penalize long wait times)
  + 0.6  * time_since_last_green   (penalize starvation)
  + 0.4  * congestion_percent      (penalize congestion)
  - 1.2  * switching_penalty       (discourage rapid oscillation)
```

**Benefits:**
- Holistic evaluation of road conditions
- Prevents starvation through fairness weighting
- Configurable weights for tuning behavior

### 2. Memory-Based Learning with Similarity Matching
**Location:** `memory_store.py` - Enhanced with new methods

**Algorithm:**
1. Convert current traffic state to numeric vector:
   - waiting_count
   - avg_waiting_time
   - congestion_percent
   - time_since_last_green
   - arrival_rate_vpm
   - departure_rate_vpm

2. Find TOP-K (default 5) similar historical states using cosine similarity

3. Retrieve rewards from matching memories

4. Compute weighted average reward per road (weighted by similarity + decay)

5. Select road with highest weighted reward

6. Fallback to composite scoring if similarity confidence < 0.7

**Key Methods:**
- `_state_to_vector()` - Converts metrics to numeric vectors
- `_cosine_similarity()` - Computes similarity between states
- `find_similar_states()` - Retrieves TOP-K matches with decay weighting
- `get_weighted_rewards_by_road()` - Aggregates learned rewards per road

### 3. Memory Decay (Temporal Adaptation)
**Location:** `memory_store.py` - `_decay_factor()` method

Implements exponential memory decay:

```
decay_factor = exp(-age_seconds / tau)
tau = 900 seconds (configurable)
```

**Purpose:**
- Older memories have less influence on decisions
- Controller adapts to changing traffic patterns
- Recent experiences weighted more heavily

### 4. Dynamic Green Duration
**Location:** `traffic_controller.py` - `_calculate_dynamic_green_duration()` method

Replaces fixed green time with dynamic calculation:

```
green_time = MIN_GREEN + ALPHA * waiting_count + BETA * avg_waiting_time
Clamped to [MIN_GREEN=10, MAX_GREEN=60] seconds

ALPHA = 1.0   (seconds per waiting vehicle)
BETA = 0.5    (seconds per second of avg wait)
```

**Benefits:**
- Light traffic: quick turnovers (MIN_GREEN)
- Heavy traffic: extended green to clear queue
- Responsive to actual demand

### 5. Gap-Out Rule
**Location:** `traffic_controller.py` - `_apply_gap_out_rule()` method

Ends green early when no waiting vehicles detected:

```
If waiting_count == 0 for GAP_OUT_THRESHOLD (3) consecutive seconds:
  End green phase immediately
```

**Benefits:**
- Improves efficiency when traffic clears
- Allows immediate switches to better-served roads
- Reduces unnecessary waiting

### 6. Starvation Protection (Fairness Guarantee)
**Location:** `traffic_controller.py` - `_apply_starvation_protection()` method

Forces service to any road red > MAX_RED_TIME (90 seconds):

```
If any road has been red > 90 seconds:
  That road MUST be served next (highest priority after emergency)
```

**Benefits:**
- Prevents unfair service deprivation
- Ensures all roads get regular green time
- Protects against network effects

### 7. Decision Method Classification
**Location:** `traffic_controller.py` - `tick_and_decide()` method

Every decision classified into method categories:

```
Method:     Priority:   Trigger:
"emergency"  1 (Highest) Ambulance detected, preempt within 5s
"starvation" 2           Road red > 90s, must be served
"memory"     3           Similar past states found (similarity >= 0.7)
"fallback"   4           Use composite scoring function
"hold"       5           Continue current green (no decision)
"gap_out"    6           No waiting vehicles for 3s, end early
```

### 8. Decision Explanations
**Location:** `traffic_controller.py` - All decision methods

Each decision generates human-readable reason string:

**Examples:**
- `"Emergency preemption: ambulance on north"`
- `"Starvation protection: west red for >90s"`
- `"Memory-based: south (reward=72.4, matches=3)"`
- `"Composite score: east (score=45.2)"`
- `"Gap-out: no waiting vehicles on south"`
- `"holding north"`

**Usage:**
- Exposed via `/api/status` decision.reason field
- Broadcast to WebSocket clients
- Enables dashboard explanation display
- Facilitates debugging and tuning

## Implementation Details

### Configuration Constants (in `TrafficController`)

```python
# Composite scoring weights
WEIGHT_QUEUE = 1.0      # Queue size impact
WEIGHT_WAIT = 0.8       # Average wait time impact
WEIGHT_FAIR = 0.6       # Fairness/starvation impact
WEIGHT_CONG = 0.4       # Congestion impact
WEIGHT_SWITCH = 1.2     # Penalty for staying green

# Green duration parameters
MIN_GREEN = 10          # Minimum green seconds
MAX_GREEN = 60          # Maximum green seconds
ALPHA = 1.0             # Coeff for waiting_count
BETA = 0.5              # Coeff for avg_wait_time
GAP_OUT_THRESHOLD = 3   # Seconds without waiting before ending

# Fairness configuration
MAX_RED_TIME = 90       # Maximum red time before forced service

# Memory-based learning
MEMORY_CONFIDENCE_THRESHOLD = 0.7  # Min similarity for memory decision
```

### Memory Store Configuration

```python
SIMILARITY_THRESHOLD = 0.5  # Min cosine similarity for valid match
TOP_K = 5                   # Number of similar states to retrieve
MEMORY_DECAY_TAU = 900      # Decay time constant (seconds)
```

## Decision Logic Priority

When deciding next green road:

1. **Emergency Preemption** (Highest Priority)
   - Active ambulance detected
   - Must switch within 5 seconds
   - Interrupts all other logic

2. **Starvation Protection**
   - Any road red > MAX_RED_TIME
   - Forces service immediately
   - Ensures fairness

3. **Memory-Based Learning**
   - Find similar past states
   - Compute weighted rewards
   - Only if confidence >= 0.7

4. **Composite Scoring** (Fallback)
   - Use multi-factor scoring function
   - Balanced approach to all metrics
   - Always available as fallback

5. **Gap-Out Rule**
   - Applied during holding phase
   - Ends green early if no traffic

## Files Modified

| File | Changes |
|------|---------|
| `memory_store.py` | Added state vectors, similarity computation, decay, TOP-K retrieval |
| `traffic_controller.py` | Added composite scoring, memory learning, dynamic duration, fairness, explanations |
| `app_sumo.py` | Updated tick_and_decide call to pass metrics parameter |

## Backward Compatibility

✅ REST API unchanged (decision.reason field enhanced)
✅ WebSocket output unchanged (reason field now more descriptive)
✅ Emergency preemption preserved (same behavior)
✅ Reward calculation unchanged
✅ Memory storage format compatible

## Testing Recommendations

### Unit Tests
- Test composite scoring with various metrics
- Verify memory decay calculations
- Test dynamic green duration bounds
- Verify starvation protection triggers

### Integration Tests
- Run simulation and observe decision reasons
- Verify memory-based decisions with similar traffic
- Test gap-out rule with light traffic
- Verify starvation protection with asymmetric load

### Behavior Validation
- Check that all four roads get served (fairness)
- Verify emergency preemption works (<5s latency)
- Confirm memory learning improves over time
- Validate decision reasons match actual decisions

## Performance Characteristics

| Operation | Complexity | Notes |
|-----------|-----------|-------|
| Composite scoring | O(4) | Constant 4 roads |
| Memory similarity | O(k*d) | k=TOP_K, d=6 dimensions |
| Memory decay | O(k) | Linear in TOP_K |
| State vector conversion | O(4) | 4 roads, 6 metrics each |
| Decision logic | O(k) | Dominated by similarity search |

## Configuration Tuning Guide

### For Aggressive (High Throughput)
- Increase WEIGHT_QUEUE, decrease WEIGHT_FAIR
- Decrease MAX_RED_TIME (e.g., 60s)
- Increase ALPHA, BETA for longer greens

### For Fair (All Roads Equal Service)
- Increase WEIGHT_FAIR
- Decrease WEIGHT_QUEUE
- Decrease MAX_RED_TIME (e.g., 45s)

### For Memory Learning
- Decrease MEMORY_CONFIDENCE_THRESHOLD (e.g., 0.5)
- Increase TOP_K (e.g., 10)
- Decrease MEMORY_DECAY_TAU for faster adaptation

## Next Steps

- Collect simulation data and analyze decision distributions
- Tune weights based on traffic patterns
- Consider machine learning for weight optimization
- Monitor memory growth and implement cleanup if needed

---
**Stage 2 Complete**: Advanced decision logic with learning, fairness, and explainability.
