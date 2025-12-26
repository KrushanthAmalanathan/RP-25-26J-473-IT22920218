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
};
