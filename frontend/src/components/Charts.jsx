import React from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import './Charts.css';

const Charts = ({ history }) => {
  if (!history || history.length === 0) {
    return (
      <div className="charts-container">
        <p className="no-data">No data available yet. Start the simulation to see charts.</p>
      </div>
    );
  }

  return (
    <div className="charts-container">
      <div className="chart-section">
        <h3>Queue Over Time</h3>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={history}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="time" label={{ value: 'Time (s)', position: 'insideBottom', offset: -5 }} />
            <YAxis label={{ value: 'Queue', angle: -90, position: 'insideLeft' }} />
            <Tooltip />
            <Legend />
            <Line type="monotone" dataKey="northQueue" stroke="#3b82f6" name="North" strokeWidth={2} />
            <Line type="monotone" dataKey="eastQueue" stroke="#10b981" name="East" strokeWidth={2} />
            <Line type="monotone" dataKey="southQueue" stroke="#f59e0b" name="South" strokeWidth={2} />
            <Line type="monotone" dataKey="westQueue" stroke="#ef4444" name="West" strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default Charts;
