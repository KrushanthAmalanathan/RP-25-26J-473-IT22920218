"""
Traffic prediction module for short-term forecasting and heavy traffic detection.

Provides lightweight, explainable predictions without ML:
- Queue trend analysis (increasing/stable/decreasing)
- Arrival rate forecasting (10s, 30s horizons)
- Heavy traffic probability heuristic
- Congestion level classification
- Predicted ETA to clear queue
"""

import math
from typing import Dict, Optional
from collections import deque
from datetime import datetime

from .state_models import Road, RoadMetricsSet, RoadMetrics


class TrafficPredictor:
    """
    Computes traffic predictions for decision biasing.
    
    Maintains per-road queue history and computes:
    - Queue trends (increasing/stable/decreasing)
    - Arrival forecasts
    - Heavy traffic probability
    - Congestion classification
    - Predicted clearance time
    """
    
    # === Configuration ===
    QUEUE_HISTORY_SIZE = 30  # Seconds of history to maintain
    TREND_THRESHOLD = 0.5    # vehicles/second threshold for trend classification
    
    # Heavy traffic probability weights
    HEAVY_WEIGHT_CONGESTION = 0.5  # Congestion impact (0-100%)
    HEAVY_WEIGHT_TREND = 0.3       # Trend impact (0-100%)
    HEAVY_WEIGHT_FLOW = 0.2        # Net flow impact (0-100%)
    
    # Congestion level thresholds
    CONGESTION_THRESHOLD_LOW = 30    # 0-30% = LOW
    CONGESTION_THRESHOLD_MEDIUM = 60  # 30-60% = MEDIUM, 60-100% = HIGH
    
    def __init__(self):
        """Initialize predictor with empty queue history."""
        self.queue_history: Dict[Road, deque] = {
            road: deque(maxlen=self.QUEUE_HISTORY_SIZE)
            for road in [Road.north, Road.east, Road.south, Road.west]
        }
        self._start_time = datetime.now()
    
    def reset(self):
        """Reset all history."""
        for road in [Road.north, Road.east, Road.south, Road.west]:
            self.queue_history[road].clear()
    
    def update_queue_history(self, current_metrics: RoadMetricsSet):
        """
        Update queue history with current waiting vehicle counts.
        Called once per simulation step.
        """
        for road in [Road.north, Road.east, Road.south, Road.west]:
            m = getattr(current_metrics, road.value)
            self.queue_history[road].append(m.waiting_count)
    
    def _compute_trend(self, road: Road) -> tuple:
        """
        Compute queue trend for a road.
        
        Returns:
            (trend_value, trend_classification)
            trend_classification in ["increasing", "stable", "decreasing"]
        """
        history = self.queue_history[road]
        
        # Need at least 2 points to compute trend
        if len(history) < 2:
            return 0.0, "stable"
        
        # Compute trend as (current - oldest) / time_span
        queue_now = history[-1]  # Most recent
        queue_old = history[0]   # Oldest
        time_span = len(history) - 1  # Seconds
        
        if time_span == 0:
            return 0.0, "stable"
        
        trend = (queue_now - queue_old) / time_span
        
        # Classify trend
        if trend > self.TREND_THRESHOLD:
            classification = "increasing"
        elif trend < -self.TREND_THRESHOLD:
            classification = "decreasing"
        else:
            classification = "stable"
        
        return trend, classification
    
    def _predict_arrivals(self, metrics: RoadMetricsSet, road: Road) -> tuple:
        """
        Predict arrivals for next 10s and 30s.
        
        arrivals = arrival_rate_vpm / X where X converts rate to timeframe.
        
        Returns:
            (arrivals_10s, arrivals_30s)
        """
        m = getattr(metrics, road.value)
        arrival_rate_vpm = m.arrival_rate_vpm
        
        # Convert rate from vehicles per minute to vehicles per second
        # then multiply by time period in seconds
        arrivals_10s = (arrival_rate_vpm / 60.0) * 10.0
        arrivals_30s = (arrival_rate_vpm / 60.0) * 30.0
        
        return arrivals_10s, arrivals_30s
    
    def _compute_heavy_traffic_probability(
        self,
        metrics: RoadMetricsSet,
        road: Road,
        trend: float
    ) -> float:
        """
        Compute heavy traffic probability using heuristic score.
        
        heavy_score = 
            0.5 * congestion_percent
          + 0.3 * normalized_trend
          + 0.2 * net_flow
        
        Returns probability 0-100%.
        """
        m = getattr(metrics, road.value)
        
        # Factor 1: Current congestion (already 0-100%)
        congestion_factor = m.congestion_percent
        
        # Factor 2: Queue trend impact
        # Normalize trend to 0-100 range
        # Assume trend ranges from -5 to +5 vehicles/sec
        # Positive trend = increasing queues = higher heavy probability
        max_trend = 5.0
        trend_normalized = max(0, min(100, (trend + max_trend) / (2 * max_trend) * 100))
        
        # Factor 3: Net flow (arrival - departure rate)
        # Positive net flow = more arriving than departing = building queue
        net_flow_rate = m.arrival_rate_vpm - m.departure_rate_vpm
        # Normalize assuming max difference of ±30 vpm
        max_flow_diff = 30.0
        flow_normalized = max(0, min(100, (net_flow_rate + max_flow_diff) / (2 * max_flow_diff) * 100))
        
        # Weighted combination
        heavy_score = (
            self.HEAVY_WEIGHT_CONGESTION * congestion_factor
            + self.HEAVY_WEIGHT_TREND * trend_normalized
            + self.HEAVY_WEIGHT_FLOW * flow_normalized
        )
        
        # Clamp to 0-100
        return max(0.0, min(100.0, heavy_score))
    
    def _classify_congestion_level(self, probability: float) -> str:
        """
        Classify congestion level based on heavy traffic probability.
        
        0-30%   → "LOW"
        30-60%  → "MEDIUM"
        60-100% → "HIGH"
        """
        if probability < self.CONGESTION_THRESHOLD_LOW:
            return "LOW"
        elif probability < self.CONGESTION_THRESHOLD_MEDIUM:
            return "MEDIUM"
        else:
            return "HIGH"
    
    def _predict_eta_clear(
        self,
        metrics: RoadMetricsSet,
        road: Road,
        trend: float,
        heavy_probability: float
    ) -> float:
        """
        Predict ETA to clear queue.
        
        If queue is increasing, multiply base ETA by (1 + heavy_probability/100).
        Otherwise, return base ETA.
        """
        m = getattr(metrics, road.value)
        base_eta = m.eta_clear_seconds
        
        # Apply adjustment only if queue is increasing
        if trend > self.TREND_THRESHOLD:
            # Increasing queue: add predicted delay
            adjusted_eta = base_eta * (1.0 + heavy_probability / 100.0)
            return min(adjusted_eta, 300.0)  # Cap at 5 minutes
        else:
            # Decreasing or stable: return base ETA
            return base_eta
    
    def predict(self, current_metrics: RoadMetricsSet) -> Dict[Road, Dict]:
        """
        Compute all predictions for all roads.
        
        Returns:
            Dict mapping Road -> {
                "queue_trend": str,
                "arrivals_10s": float,
                "arrivals_30s": float,
                "heavy_traffic_probability": float,
                "congestion_level": str,
                "predicted_eta_clear_seconds": float
            }
        """
        # Update history with current metrics
        self.update_queue_history(current_metrics)
        
        predictions = {}
        
        for road in [Road.north, Road.east, Road.south, Road.west]:
            # Compute all prediction components
            trend, trend_class = self._compute_trend(road)
            arrivals_10s, arrivals_30s = self._predict_arrivals(current_metrics, road)
            heavy_prob = self._compute_heavy_traffic_probability(current_metrics, road, trend)
            congestion_level = self._classify_congestion_level(heavy_prob)
            predicted_eta = self._predict_eta_clear(current_metrics, road, trend, heavy_prob)
            
            predictions[road] = {
                "queue_trend": trend_class,
                "arrivals_10s": round(arrivals_10s, 2),
                "arrivals_30s": round(arrivals_30s, 2),
                "heavy_traffic_probability": round(heavy_prob, 1),
                "congestion_level": congestion_level,
                "predicted_eta_clear_seconds": round(predicted_eta, 2),
            }
        
        return predictions
    
    def get_prediction_bias_for_road(
        self,
        road: Road,
        predictions: Dict[Road, Dict],
        weight: float = 0.3
    ) -> float:
        """
        Compute prediction bias for decision scoring.
        
        Bias = weight * heavy_traffic_probability
        
        This encourages the controller to serve roads with predicted heavy traffic.
        """
        if road not in predictions:
            return 0.0
        
        heavy_prob = predictions[road].get("heavy_traffic_probability", 0.0)
        return weight * heavy_prob
