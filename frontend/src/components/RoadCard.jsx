import React from 'react';
import './RoadCard.css';

const RoadCard = ({ road, data }) => {
  const { car, bike, bus, truck, lorry, auto } = data;
  const queue = (car * 2) + (bike * 1) + (auto * 2) + (bus * 4) + (truck * 4) + (lorry * 4);

  const getCongestionLevel = (q) => {
    if (q < 10) return { label: 'Low', color: '#10b981' };
    if (q < 30) return { label: 'Medium', color: '#f59e0b' };
    return { label: 'High', color: '#ef4444' };
  };

  const congestion = getCongestionLevel(queue);

  return (
    <div className="road-card">
      <div className="road-header">
        <h3>{road.toUpperCase()}</h3>
        <div className="congestion-badge" style={{ backgroundColor: congestion.color }}>
          {congestion.label}
        </div>
      </div>
      <div className="vehicle-counts">
        <div className="count-item">
          <span className="icon">🚗</span>
          <span className="label">Car:</span>
          <span className="value">{car}</span>
        </div>
        <div className="count-item">
          <span className="icon">🚲</span>
          <span className="label">Bike:</span>
          <span className="value">{bike}</span>
        </div>
        <div className="count-item">
          <span className="icon">🚌</span>
          <span className="label">Bus:</span>
          <span className="value">{bus}</span>
        </div>
        <div className="count-item">
          <span className="icon">🚛</span>
          <span className="label">Truck:</span>
          <span className="value">{truck}</span>
        </div>
        <div className="count-item">
          <span className="icon">🚚</span>
          <span className="label">Lorry:</span>
          <span className="value">{lorry}</span>
        </div>
        <div className="count-item">
          <span className="icon">🛺</span>
          <span className="label">Auto:</span>
          <span className="value">{auto}</span>
        </div>
      </div>
      <div className="queue-score">
        <span>Queue Score:</span>
        <strong>{queue}</strong>
      </div>
    </div>
  );
};

export default RoadCard;
