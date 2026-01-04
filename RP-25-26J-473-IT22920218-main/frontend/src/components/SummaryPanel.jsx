import React from 'react';
import './SummaryPanel.css';

const SummaryPanel = ({ status }) => {
  if (!status || !status.metrics) {
    return <div className="summary-panel">Loading summary...</div>;
  }

  const { metrics, prediction } = status;

  // Calculate total waiting vehicles
  const totalWaiting = (metrics.north?.waiting_count || 0) +
                       (metrics.east?.waiting_count || 0) +
                       (metrics.south?.waiting_count || 0) +
                       (metrics.west?.waiting_count || 0);

  // Calculate total cleared last interval
  const totalCleared = (metrics.north?.cleared_last_interval || 0) +
                       (metrics.east?.cleared_last_interval || 0) +
                       (metrics.south?.cleared_last_interval || 0) +
                       (metrics.west?.cleared_last_interval || 0);

  // Find worst congestion road
  const roads = ['north', 'east', 'south', 'west'];
  let worstRoad = 'north';
  let maxProbability = 0;

  if (prediction) {
    roads.forEach(road => {
      const prob = prediction[road]?.heavy_traffic_probability || 0;
      if (prob > maxProbability) {
        maxProbability = prob;
        worstRoad = road;
      }
    });
  }

  // Calculate global congestion level
  const avgProbability = prediction 
    ? (
        (prediction.north?.heavy_traffic_probability || 0) +
        (prediction.east?.heavy_traffic_probability || 0) +
        (prediction.south?.heavy_traffic_probability || 0) +
        (prediction.west?.heavy_traffic_probability || 0)
      ) / 4
    : 0;

  const getGlobalLevel = (avg) => {
    if (avg > 60) return { label: 'HIGH', color: '#ef4444' };
    if (avg > 30) return { label: 'MEDIUM', color: '#f59e0b' };
    return { label: 'LOW', color: '#10b981' };
  };

  const globalLevel = getGlobalLevel(avgProbability);

  return (
    <div className="summary-panel">
      <h2 className="summary-title">📊 Intersection Summary</h2>
      
      <div className="summary-grid">
        <div className="summary-card">
          <div className="summary-icon">🚗</div>
          <div className="summary-content">
            <div className="summary-value">{totalWaiting}</div>
            <div className="summary-label">Total Waiting</div>
          </div>
        </div>

        <div className="summary-card">
          <div className="summary-icon">✅</div>
          <div className="summary-content">
            <div className="summary-value">{totalCleared}</div>
            <div className="summary-label">Cleared (Last 5s)</div>
          </div>
        </div>

        <div className="summary-card">
          <div className="summary-icon">⚠️</div>
          <div className="summary-content">
            <div className="summary-value">{worstRoad.toUpperCase()}</div>
            <div className="summary-label">Worst Congestion</div>
            <div className="summary-sublabel">{maxProbability.toFixed(0)}% probability</div>
          </div>
        </div>

        <div className="summary-card">
          <div className="summary-icon">🌍</div>
          <div className="summary-content">
            <div 
              className="summary-badge"
              style={{ backgroundColor: globalLevel.color }}
            >
              {globalLevel.label}
            </div>
            <div className="summary-label">Global Level</div>
            <div className="summary-sublabel">{avgProbability.toFixed(1)}% avg</div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SummaryPanel;
