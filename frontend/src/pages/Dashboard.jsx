import React, { useState, useEffect, useRef } from 'react';
import { httpClient } from '../api/httpClient';
import { WebSocketClient } from '../api/wsClient';
import RoadCard from '../components/RoadCard';
import SignalStatus from '../components/SignalStatus';
import EmergencyBanner from '../components/EmergencyBanner';
import Charts from '../components/Charts';
import JunctionView from '../components/JunctionView';
import './Dashboard.css';

const Dashboard = () => {
  const [status, setStatus] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [history, setHistory] = useState([]);
  const wsClient = useRef(null);

  useEffect(() => {
    // Fetch initial status
    httpClient.getStatus().then(setStatus).catch(console.error);

    // Connect WebSocket
    wsClient.current = new WebSocketClient(
      (data) => {
        setStatus(data);
        // Add to history (keep last 60 data points)
        setHistory((prev) => {
          const newHistory = [...prev, {
            time: data.time,
            northQueue: data.queues?.north || 0,
            eastQueue: data.queues?.east || 0,
            southQueue: data.queues?.south || 0,
            westQueue: data.queues?.west || 0,
          }];
          return newHistory.slice(-60);
        });
      },
      (error) => console.error('WS Error:', error),
      () => console.log('WS Closed')
    );
    wsClient.current.connect();

    return () => {
      if (wsClient.current) {
        wsClient.current.disconnect();
      }
    };
  }, []);

  const handleStart = async () => {
    try {
      await httpClient.startSimulation();
      setIsRunning(true);
      setHistory([]); // Reset history on new run
    } catch (err) {
      console.error('Failed to start simulation:', err);
    }
  };

  const handleStop = async () => {
    try {
      await httpClient.stopSimulation();
      setIsRunning(false);
    } catch (err) {
      console.error('Failed to stop simulation:', err);
    }
  };

  if (!status) {
    return <div className="loading">Loading...</div>;
  }

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>Smart Traffic Control System</h1>
        <div className="controls">
          <button 
            className="btn btn-start" 
            onClick={handleStart}
            disabled={isRunning}
          >
            ▶ Start
          </button>
          <button 
            className="btn btn-stop" 
            onClick={handleStop}
            disabled={!isRunning}
          >
            ■ Stop
          </button>
        </div>
      </header>

      <div className="status-bar">
        <div className="status-item">
          <span className="label">Mode:</span>
          <span className="value">{status.emergency?.active ? 'Emergency Preemption' : 'Normal'}</span>
        </div>
        <div className="status-item">
          <span className="label">Time:</span>
          <span className="value">{status.time}s</span>
        </div>
        <div className="status-item">
          <span className="label">Decision:</span>
          <span className="value">{status.decision?.method || 'N/A'}</span>
        </div>
      </div>

      <EmergencyBanner emergency={status.emergency} />

      <div className="main-grid">
        <div className="left-panel">
          <JunctionView counts={status.counts} signal={status.signal} />
          <SignalStatus signal={status.signal} />
        </div>

        <div className="right-panel">
          <div className="roads-grid">
            <RoadCard road="north" data={status.counts?.north || {}} />
            <RoadCard road="east" data={status.counts?.east || {}} />
            <RoadCard road="south" data={status.counts?.south || {}} />
            <RoadCard road="west" data={status.counts?.west || {}} />
          </div>
        </div>
      </div>

      <div className="decision-info">
        <h3>Decision Reason</h3>
        <p>{status.decision?.reason || 'No decision info available'}</p>
      </div>

      <Charts history={history} />
    </div>
  );
};

export default Dashboard;
