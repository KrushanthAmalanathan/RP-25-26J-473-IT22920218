import React from 'react';
import './ExplainabilityPanel.css';

const ExplainabilityPanel = ({ status }) => {
  if (!status || !status.decision || !status.signal) {
    return <div className="explainability-panel">No decision data</div>;
  }

  const { decision, signal } = status;
  const { method, reason } = decision;
  const { greenRoad, remaining } = signal;

  // Get method badge color
  const getMethodColor = (method) => {
    switch (method) {
      case 'emergency':
        return '#ef4444';
      case 'starvation':
        return '#f59e0b';
      case 'memory':
        return '#8b5cf6';
      case 'fallback':
        return '#3b82f6';
      case 'gap_out':
        return '#10b981';
      case 'hold':
        return '#6b7280';
      default:
        return '#9ca3af';
    }
  };

  // Get method icon
  const getMethodIcon = (method) => {
    switch (method) {
      case 'emergency':
        return '🚨';
      case 'starvation':
        return '⏰';
      case 'memory':
        return '🧠';
      case 'fallback':
        return '⚖️';
      case 'gap_out':
        return '✂️';
      case 'hold':
        return '⏸️';
      default:
        return '❓';
    }
  };

  return (
    <div className="explainability-panel">
      <h2 className="explainability-title">💡 Decision Explainability</h2>

      <div className="decision-grid">
        <div className="decision-card">
          <div className="decision-header">
            <span className="decision-icon">{getMethodIcon(method)}</span>
            <h3>Decision Method</h3>
          </div>
          <div 
            className="decision-method-badge"
            style={{ backgroundColor: getMethodColor(method) }}
          >
            {method?.toUpperCase() || 'UNKNOWN'}
          </div>
        </div>

        <div className="decision-card">
          <div className="decision-header">
            <span className="decision-icon">🚦</span>
            <h3>Current Green</h3>
          </div>
          <div className="current-green">
            <span className="green-road">{greenRoad?.toUpperCase() || 'N/A'}</span>
            <span className="remaining-time">{remaining}s remaining</span>
          </div>
        </div>
      </div>

      <div className="reason-card">
        <div className="reason-header">
          <span className="decision-icon">📝</span>
          <h3>Explanation</h3>
        </div>
        <p className="reason-text">{reason || 'No explanation available'}</p>
      </div>

      <div className="legend">
        <h4>Decision Methods:</h4>
        <div className="legend-items">
          <div className="legend-item">
            <span className="legend-dot" style={{ backgroundColor: '#ef4444' }}></span>
            <span>Emergency: Ambulance preemption</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot" style={{ backgroundColor: '#f59e0b' }}></span>
            <span>Starvation: Fairness guarantee</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot" style={{ backgroundColor: '#8b5cf6' }}></span>
            <span>Memory: Past experience</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot" style={{ backgroundColor: '#3b82f6' }}></span>
            <span>Fallback: Composite score</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot" style={{ backgroundColor: '#10b981' }}></span>
            <span>Gap-out: No waiting vehicles</span>
          </div>
          <div className="legend-item">
            <span className="legend-dot" style={{ backgroundColor: '#6b7280' }}></span>
            <span>Hold: Continuing current phase</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ExplainabilityPanel;
