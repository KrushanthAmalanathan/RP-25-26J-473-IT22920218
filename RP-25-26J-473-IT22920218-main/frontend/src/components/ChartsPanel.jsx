import React, { useState } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import './ChartsPanel.css';

const ChartsPanel = ({ history }) => {
  const [selectedRoad, setSelectedRoad] = useState('all');

  if (!history || history.length === 0) {
    return <div className="charts-panel">Waiting for data...</div>;
  }

  // Prepare data for charts
  const chartData = history.map(item => ({
    time: item.time,
    totalQueue: (item.northQueue || 0) + (item.eastQueue || 0) + 
                (item.southQueue || 0) + (item.westQueue || 0),
    northProb: item.northProb || 0,
    eastProb: item.eastProb || 0,
    southProb: item.southProb || 0,
    westProb: item.westProb || 0,
    northETA: item.northETA || 0,
    eastETA: item.eastETA || 0,
    southETA: item.southETA || 0,
    westETA: item.westETA || 0,
  }));

  return (
    <div className="charts-panel">
      <h2 className="charts-title">📈 Live Analytics</h2>

      {/* Total Queue Over Time */}
      <div className="chart-container">
        <h3 className="chart-subtitle">Total Queue Over Time</h3>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis 
              dataKey="time" 
              stroke="#6b7280"
              tick={{ fontSize: 12 }}
            />
            <YAxis 
              stroke="#6b7280"
              tick={{ fontSize: 12 }}
              label={{ value: 'Vehicles', angle: -90, position: 'insideLeft', style: { fontSize: 12 } }}
            />
            <Tooltip 
              contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px' }}
            />
            <Legend />
            <Line 
              type="monotone" 
              dataKey="totalQueue" 
              stroke="#3b82f6" 
              strokeWidth={2}
              dot={false}
              name="Total Queue"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Heavy Traffic Probability */}
      <div className="chart-container">
        <div className="chart-header">
          <h3 className="chart-subtitle">Heavy Traffic Probability (%)</h3>
          <select 
            className="road-selector"
            value={selectedRoad}
            onChange={(e) => setSelectedRoad(e.target.value)}
          >
            <option value="all">All Roads</option>
            <option value="north">North</option>
            <option value="east">East</option>
            <option value="south">South</option>
            <option value="west">West</option>
          </select>
        </div>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis 
              dataKey="time" 
              stroke="#6b7280"
              tick={{ fontSize: 12 }}
            />
            <YAxis 
              stroke="#6b7280"
              tick={{ fontSize: 12 }}
              domain={[0, 100]}
              label={{ value: 'Probability (%)', angle: -90, position: 'insideLeft', style: { fontSize: 12 } }}
            />
            <Tooltip 
              contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px' }}
            />
            <Legend />
            {(selectedRoad === 'all' || selectedRoad === 'north') && (
              <Line 
                type="monotone" 
                dataKey="northProb" 
                stroke="#ef4444" 
                strokeWidth={2}
                dot={false}
                name="North"
              />
            )}
            {(selectedRoad === 'all' || selectedRoad === 'east') && (
              <Line 
                type="monotone" 
                dataKey="eastProb" 
                stroke="#f59e0b" 
                strokeWidth={2}
                dot={false}
                name="East"
              />
            )}
            {(selectedRoad === 'all' || selectedRoad === 'south') && (
              <Line 
                type="monotone" 
                dataKey="southProb" 
                stroke="#10b981" 
                strokeWidth={2}
                dot={false}
                name="South"
              />
            )}
            {(selectedRoad === 'all' || selectedRoad === 'west') && (
              <Line 
                type="monotone" 
                dataKey="westProb" 
                stroke="#3b82f6" 
                strokeWidth={2}
                dot={false}
                name="West"
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Predicted ETA */}
      <div className="chart-container">
        <h3 className="chart-subtitle">Predicted ETA to Clear (seconds)</h3>
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis 
              dataKey="time" 
              stroke="#6b7280"
              tick={{ fontSize: 12 }}
            />
            <YAxis 
              stroke="#6b7280"
              tick={{ fontSize: 12 }}
              label={{ value: 'Seconds', angle: -90, position: 'insideLeft', style: { fontSize: 12 } }}
            />
            <Tooltip 
              contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px' }}
            />
            <Legend />
            <Line 
              type="monotone" 
              dataKey="northETA" 
              stroke="#ef4444" 
              strokeWidth={1.5}
              dot={false}
              name="North"
            />
            <Line 
              type="monotone" 
              dataKey="eastETA" 
              stroke="#f59e0b" 
              strokeWidth={1.5}
              dot={false}
              name="East"
            />
            <Line 
              type="monotone" 
              dataKey="southETA" 
              stroke="#10b981" 
              strokeWidth={1.5}
              dot={false}
              name="South"
            />
            <Line 
              type="monotone" 
              dataKey="westETA" 
              stroke="#3b82f6" 
              strokeWidth={1.5}
              dot={false}
              name="West"
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default ChartsPanel;
