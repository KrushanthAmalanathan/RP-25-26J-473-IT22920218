import React from 'react';
import './JunctionView.css';

const JunctionView = ({ counts, signal, actualGreenRoads }) => {
  const getRoadColor = (road) => {
    // Use actual SUMO green if available, otherwise fall back to controller decision
    const greenRoads = actualGreenRoads || [];
    if (greenRoads.length > 0) {
      return greenRoads.includes(road) ? '#10b981' : '#ef4444';
    }
    // Fallback to controller decision
    return signal?.greenRoad === road ? '#10b981' : '#ef4444';
  };

  return (
    <div className="junction-view">
      <h3>Junction Overview</h3>
      <div className="junction-grid">
        <div className="road-visual north" style={{ borderColor: getRoadColor('north') }}>
          <span className="road-label">NORTH</span>
          <span className="vehicle-count">{Object.values(counts?.north || {}).reduce((a, b) => a + b, 0)}</span>
        </div>
        <div className="road-visual east" style={{ borderColor: getRoadColor('east') }}>
          <span className="road-label">EAST</span>
          <span className="vehicle-count">{Object.values(counts?.east || {}).reduce((a, b) => a + b, 0)}</span>
        </div>
        <div className="road-visual south" style={{ borderColor: getRoadColor('south') }}>
          <span className="road-label">SOUTH</span>
          <span className="vehicle-count">{Object.values(counts?.south || {}).reduce((a, b) => a + b, 0)}</span>
        </div>
        <div className="road-visual west" style={{ borderColor: getRoadColor('west') }}>
          <span className="road-label">WEST</span>
          <span className="vehicle-count">{Object.values(counts?.west || {}).reduce((a, b) => a + b, 0)}</span>
        </div>
        <div className="junction-center">
          <div className="traffic-light"></div>
        </div>
      </div>
    </div>
  );
};

export default JunctionView;
