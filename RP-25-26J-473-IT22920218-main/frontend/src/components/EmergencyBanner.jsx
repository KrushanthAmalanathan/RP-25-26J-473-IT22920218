import React from 'react';
import './EmergencyBanner.css';

const EmergencyBanner = ({ emergency }) => {
  if (!emergency?.active) return null;

  return (
    <div className="emergency-banner">
      <div className="emergency-icon">🚨</div>
      <div className="emergency-message">
        <strong>EMERGENCY DETECTED</strong>
        <span>Preemption active on {emergency.road?.toUpperCase()} road</span>
      </div>
    </div>
  );
};

export default EmergencyBanner;
