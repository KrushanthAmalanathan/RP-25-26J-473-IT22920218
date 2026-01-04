const API_BASE = 'http://localhost:8000';

export const httpClient = {
  async getStatus() {
    const response = await fetch(`${API_BASE}/api/status`);
    return response.json();
  },

  async getMemorySummary() {
    const response = await fetch(`${API_BASE}/api/memory/summary`);
    return response.json();
  },

  async startSimulation() {
    const response = await fetch(`${API_BASE}/api/control/start`, {
      method: 'POST',
    });
    return response.json();
  },

  async stopSimulation() {
    const response = await fetch(`${API_BASE}/api/control/stop`, {
      method: 'POST',
    });
    return response.json();
  },

  // Manual Control APIs
  async getControlMode() {
    const response = await fetch(`${API_BASE}/api/control/mode`);
    return response.json();
  },

  async setControlMode(mode) {
    const response = await fetch(`${API_BASE}/api/control/mode`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode }),
    });
    return response.json();
  },

  async applyManualControl(command, duration) {
    const response = await fetch(`${API_BASE}/api/control/manual/apply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command, duration }),
    });
    return response.json();
  },

  async cancelManualControl() {
    const response = await fetch(`${API_BASE}/api/control/manual/cancel`, {
      method: 'POST',
    });
    return response.json();
  },
};
