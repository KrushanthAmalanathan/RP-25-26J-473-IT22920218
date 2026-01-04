import React, { useState, useEffect, useRef } from 'react';
import { httpClient } from '../api/httpClient';
import { WebSocketClient } from '../api/wsClient';
import RoadCard from '../components/RoadCard';
import SignalStatus from '../components/SignalStatus';
import EmergencyBanner from '../components/EmergencyBanner';
import Charts from '../components/Charts';
import JunctionView from '../components/JunctionView';
import SummaryPanel from '../components/SummaryPanel';
import ChartsPanel from '../components/ChartsPanel';
import ExplainabilityPanel from '../components/ExplainabilityPanel';
import ManualOverridePanel from '../components/ManualOverridePanel';
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
        // Add to history (keep last 60 data points) with prediction data
        setHistory((prev) => {
          const newHistory = [...prev, {
            time: data.time,
            northQueue: data.queues?.north || 0,
            eastQueue: data.queues?.east || 0,
            southQueue: data.queues?.south || 0,
            westQueue: data.queues?.west || 0,
            northProb: data.prediction?.north?.heavy_traffic_probability || 0,
            eastProb: data.prediction?.east?.heavy_traffic_probability || 0,
            southProb: data.prediction?.south?.heavy_traffic_probability || 0,
            westProb: data.prediction?.west?.heavy_traffic_probability || 0,
            northETA: data.prediction?.north?.predicted_eta_clear_seconds || 0,
            eastETA: data.prediction?.east?.predicted_eta_clear_seconds || 0,
            southETA: data.prediction?.south?.predicted_eta_clear_seconds || 0,
            westETA: data.prediction?.west?.predicted_eta_clear_seconds || 0,
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

      {/* Stage 4: Summary Panel */}
      <SummaryPanel status={status} />

      {/* Stage 4: Explainability Panel */}
      <ExplainabilityPanel status={status} />

      {/* Stage 5: Manual Override Panel */}
      <ManualOverridePanel status={status} />

      <div className="main-grid">
        <div className="left-panel">
          <JunctionView 
            counts={status.counts} 
            signal={status.signal}
            actualGreenRoads={status.actual_green_roads}
          />
          <SignalStatus 
            signal={status.signal}
            actualGreenRoads={status.actual_green_roads}
            actualGreenGroup={status.actual_green_group}
          />
        </div>

        <div className="right-panel">
          <div className="roads-grid">
            <RoadCard 
              road="north" 
              data={status.counts?.north || {}} 
              metrics={status.metrics?.north}
              prediction={status.prediction?.north}
            />
            <RoadCard 
              road="east" 
              data={status.counts?.east || {}} 
              metrics={status.metrics?.east}
              prediction={status.prediction?.east}
            />
            <RoadCard 
              road="south" 
              data={status.counts?.south || {}} 
              metrics={status.metrics?.south}
              prediction={status.prediction?.south}
            />
            <RoadCard 
              road="west" 
              data={status.counts?.west || {}} 
              metrics={status.metrics?.west}
              prediction={status.prediction?.west}
            />
          </div>
        </div>
      </div>

      {/* Old Charts (keep for compatibility) */}
      <Charts history={history} />

      {/* Stage 4: New Charts Panel */}
      <ChartsPanel history={history} />
    </div>
  );
};

export default Dashboard;
