import React from 'react';
import './PredictionPanel.css';

const PredictionPanel = ({ prediction }) => {
  if (!prediction) {
    return <div className="prediction-panel">No prediction data</div>;
  }

  const {
    queue_trend = 'stable',
    heavy_traffic_probability = 0,
    congestion_level = 'LOW',
    arrivals_10s = 0,
    arrivals_30s = 0,
    predicted_eta_clear_seconds = 0,
  } = prediction;

  // Get badge color for queue trend
  const getTrendColor = (trend) => {
    if (trend === 'increasing') return '#ef4444';
    if (trend === 'decreasing') return '#10b981';
    return '#6b7280';
  };

  // Get color for congestion level
  const getCongestionColor = (level) => {
    if (level === 'HIGH') return '#ef4444';
    if (level === 'MEDIUM') return '#f59e0b';
    return '#10b981';
  };

  // Format ETA as mm:ss
  const formatETA = (seconds) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="prediction-panel">
      <h4 className="prediction-header">🔮 Predictions</h4>
      
      <div className="prediction-row">
        <span className="prediction-label">Queue Trend:</span>
        <span 
          className="prediction-badge" 
          style={{ backgroundColor: getTrendColor(queue_trend) }}
        >
          {queue_trend}
        </span>
      </div>

      <div className="prediction-row">
        <span className="prediction-label">Congestion:</span>
        <span 
          className="prediction-badge" 
          style={{ backgroundColor: getCongestionColor(congestion_level) }}
        >
          {congestion_level}
        </span>
      </div>

      <div className="prediction-row">
        <span className="prediction-label">Heavy Traffic:</span>
        <div className="probability-container">
          <div className="probability-bar">
            <div 
              className="probability-fill" 
              style={{ 
                width: `${heavy_traffic_probability}%`,
                backgroundColor: getCongestionColor(
                  heavy_traffic_probability > 60 ? 'HIGH' : 
                  heavy_traffic_probability > 30 ? 'MEDIUM' : 'LOW'
                )
              }}
            />
          </div>
          <span className="probability-value">{heavy_traffic_probability.toFixed(0)}%</span>
        </div>
      </div>

      <div className="prediction-row">
        <span className="prediction-label">Arrivals (10s):</span>
        <span className="prediction-value">{arrivals_10s.toFixed(1)} veh</span>
      </div>

      <div className="prediction-row">
        <span className="prediction-label">Arrivals (30s):</span>
        <span className="prediction-value">{arrivals_30s.toFixed(1)} veh</span>
      </div>

      <div className="prediction-row">
        <span className="prediction-label">Predicted ETA:</span>
        <span className="prediction-value">{formatETA(predicted_eta_clear_seconds)}</span>
      </div>
    </div>
  );
};

export default PredictionPanel;
