import React from 'react';
import './SignalStatus.css';

const SignalStatus = ({ signal, actualGreenRoads, actualGreenGroup }) => {
  const { greenRoad, remaining } = signal;
  
  // Determine which roads are actually green in SUMO
  const isRoadGreen = (road) => {
    if (actualGreenRoads && actualGreenRoads.length > 0) {
      return actualGreenRoads.includes(road);
    }
    // Fallback to controller decision
    return greenRoad === road;
  };

  return (
    <div className="signal-status">
      <h3>Traffic Signal Status</h3>
      <div className="signal-info">
        <div className="current-green">
          <span className="label">Controller Decision:</span>
          <span className="green-road">{greenRoad?.toUpperCase() || 'NONE'}</span>
        </div>
        {actualGreenGroup && (
          <div className="actual-green">
            <span className="label">SUMO Actual Green:</span>
            <span className="green-road">{actualGreenGroup}</span>
          </div>
        )}
        <div className="countdown">
          <span className="label">Remaining:</span>
          <span className="time">{remaining}s</span>
        </div>
      </div>
      <div className="signal-lights">
        <div className={`light ${isRoadGreen('north') ? 'active' : ''}`}>N</div>
        <div className={`light ${isRoadGreen('east') ? 'active' : ''}`}>E</div>
        <div className={`light ${isRoadGreen('south') ? 'active' : ''}`}>S</div>
        <div className={`light ${isRoadGreen('west') ? 'active' : ''}`}>W</div>
      </div>
    </div>
  );
};

export default SignalStatus;
