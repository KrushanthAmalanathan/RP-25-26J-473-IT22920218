import React from 'react';
import './SignalStatus.css';

const SignalStatus = ({ signal }) => {
  const { greenRoad, remaining } = signal;

  return (
    <div className="signal-status">
      <h3>Traffic Signal Status</h3>
      <div className="signal-info">
        <div className="current-green">
          <span className="label">Current Green:</span>
          <span className="green-road">{greenRoad?.toUpperCase() || 'NONE'}</span>
        </div>
        <div className="countdown">
          <span className="label">Remaining:</span>
          <span className="time">{remaining}s</span>
        </div>
      </div>
      <div className="signal-lights">
        <div className={`light ${greenRoad === 'north' ? 'active' : ''}`}>N</div>
        <div className={`light ${greenRoad === 'east' ? 'active' : ''}`}>E</div>
        <div className={`light ${greenRoad === 'south' ? 'active' : ''}`}>S</div>
        <div className={`light ${greenRoad === 'west' ? 'active' : ''}`}>W</div>
      </div>
    </div>
  );
};

export default SignalStatus;
