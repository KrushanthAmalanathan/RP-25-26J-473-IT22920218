import React, { useState, useEffect } from 'react';
import './ManualOverridePanel.css';
import { httpClient } from '../api/httpClient';

const ManualOverridePanel = ({ status }) => {
  const [mode, setMode] = useState('AUTO');
  const [selectedAction, setSelectedAction] = useState(null);
  const [duration, setDuration] = useState(30);
  const [message, setMessage] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  // Update mode from backend status
  useEffect(() => {
    if (status?.mode) {
      setMode(status.mode);
    }
  }, [status]);

  const showMessage = (text, type = 'info') => {
    setMessage({ text, type });
    setTimeout(() => setMessage(null), 5000);
  };

  const handleModeToggle = async () => {
    const newMode = mode === 'AUTO' ? 'MANUAL' : 'AUTO';
    setIsLoading(true);
    
    try {
      const result = await httpClient.setControlMode(newMode);
      setMode(result.mode);
      setSelectedAction(null);
      showMessage(`Switched to ${result.mode} mode`, 'success');
    } catch (error) {
      showMessage(`Error: ${error.message}`, 'error');
    } finally {
      setIsLoading(false);
    }
  };

  const handleAction = async (action) => {
    if (mode !== 'MANUAL') {
      showMessage('Switch to MANUAL mode first', 'warning');
      return;
    }

    if (status?.emergency?.active) {
      showMessage('Cannot use manual control during emergency', 'error');
      return;
    }

    setIsLoading(true);
    setSelectedAction(action);
    
    try {
      const result = await httpClient.applyManualControl(action, duration);
      showMessage(result.message, result.status === 'success' ? 'success' : 'error');
    } catch (error) {
      showMessage(`Error: ${error.message}`, 'error');
    } finally {
      setIsLoading(false);
    }
  };

  const handleCancel = async () => {
    setIsLoading(true);
    
    try {
      const result = await httpClient.cancelManualControl();
      setMode('AUTO');
      setSelectedAction(null);
      showMessage(result.message, 'success');
    } catch (error) {
      showMessage(`Error: ${error.message}`, 'error');
    } finally {
      setIsLoading(false);
    }
  };

  const isEmergencyActive = status?.emergency?.active || false;
  const manualActive = status?.manual?.active || false;
  const manualRemaining = status?.manual?.remaining_seconds || 0;
  const currentCommand = status?.manual?.command || null;

  return (
    <div className="manual-override-panel">
      <h2 className="override-title">🎮 Manual Override</h2>

      {message && (
        <div className={`message-banner ${message.type}`}>
          {message.text}
        </div>
      )}

      <div className="mode-toggle-container">
        <button 
          className={`mode-toggle ${mode === 'AUTO' ? 'active' : ''}`}
          onClick={handleModeToggle}
          disabled={isLoading || isEmergencyActive}
        >
          <span className="mode-icon">🤖</span>
          <span className="mode-label">AUTO</span>
        </button>
        <button 
          className={`mode-toggle ${mode === 'MANUAL' ? 'active' : ''}`}
          onClick={handleModeToggle}
          disabled={isLoading || isEmergencyActive}
        >
          <span className="mode-icon">👤</span>
          <span className="mode-label">MANUAL</span>
        </button>
      </div>

      <div className={`control-panel ${mode === 'MANUAL' ? 'enabled' : 'disabled'}`}>
        <div className="duration-selector">
          <label htmlFor="duration">Duration:</label>
          <select 
            id="duration" 
            value={duration} 
            onChange={(e) => setDuration(Number(e.target.value))}
            disabled={mode === 'AUTO' || isLoading || isEmergencyActive}
          >
            <option value={10}>10 seconds</option>
            <option value={20}>20 seconds</option>
            <option value={30}>30 seconds</option>
            <option value={45}>45 seconds</option>
            <option value={60}>60 seconds</option>
            <option value={90}>90 seconds</option>
            <option value={120}>120 seconds</option>
          </select>
        </div>

        <div className="control-buttons">
          <button
            className={`control-btn ns-green ${currentCommand === 'NS_GREEN' ? 'active' : ''}`}
            onClick={() => handleAction('NS_GREEN')}
            disabled={mode === 'AUTO' || isLoading || isEmergencyActive}
          >
            <span className="btn-icon">🚦</span>
            <span className="btn-label">Force NS Green</span>
            <span className="btn-sublabel">North + South</span>
          </button>

          <button
            className={`control-btn ew-green ${currentCommand === 'EW_GREEN' ? 'active' : ''}`}
            onClick={() => handleAction('EW_GREEN')}
            disabled={mode === 'AUTO' || isLoading || isEmergencyActive}
          >
            <span className="btn-icon">🚦</span>
            <span className="btn-label">Force EW Green</span>
            <span className="btn-sublabel">East + West</span>
          </button>

          <button
            className={`control-btn all-red ${currentCommand === 'ALL_RED' ? 'active' : ''}`}
            onClick={() => handleAction('ALL_RED')}
            disabled={mode === 'AUTO' || isLoading || isEmergencyActive}
          >
            <span className="btn-icon">🛑</span>
            <span className="btn-label">All Red</span>
            <span className="btn-sublabel">Emergency Stop</span>
          </button>
        </div>

        {manualActive && manualRemaining > 0 && (
          <div className="countdown-display">
            <span className="countdown-icon">⏱️</span>
            <span className="countdown-text">
              Manual control active: <strong>{currentCommand}</strong>
            </span>
            <span className="countdown-time">{manualRemaining}s remaining</span>
            <button 
              className="cancel-btn" 
              onClick={handleCancel}
              disabled={isLoading}
            >
              Return to AUTO
            </button>
          </div>
        )}

        {mode === 'MANUAL' && !manualActive && (
          <div className="warning-banner">
            <span className="warning-icon">⚠️</span>
            <div className="warning-content">
              <strong>Manual Mode Ready</strong>
              <p>Select a control action and duration above.</p>
            </div>
          </div>
        )}

        {mode === 'AUTO' && (
          <div className="info-banner">
            <span className="info-icon">ℹ️</span>
            <div className="info-content">
              <strong>Automatic Mode</strong>
              <p>System is optimizing traffic flow automatically.</p>
            </div>
          </div>
        )}

        {isEmergencyActive && (
          <div className="emergency-block-banner">
            <span className="emergency-icon">🚨</span>
            <div className="emergency-content">
              <strong>Emergency Override</strong>
              <p>Manual control disabled during emergency response.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ManualOverridePanel;
