import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer
} from 'recharts';
import axios from 'axios';
import { useNavControls } from '../App';

function ist() {
  const n = new Date();
  return new Date(n.getTime() + n.getTimezoneOffset() * 60000 + 5.5 * 3600000);
}
function fsh(d) {
  const h = d.getHours(), m = d.getMinutes(), a = h >= 12 ? 'p' : 'a';
  return `${h % 12 || 12}:${m.toString().padStart(2,'0')}${a}`;
}

const Home = () => {
  const { setNavControls } = useNavControls();

  const [sensorData, setSensorData]             = useState([]);
  const [nodes, setNodes]                       = useState([]);
  const [selectedNode, setSelectedNode]         = useState('');
  const [selectedNodeData, setSelectedNodeData] = useState(null);
  const [loading, setLoading]                   = useState(true);
  const [lastUpdated, setLastUpdated]           = useState('--');
  const [hasData, setHasData]                   = useState(false);
  const [statusMsg, setStatusMsg]               = useState('');
  const [timeRange, setTimeRange]               = useState('all');
  const [refreshMs, setRefreshMs]               = useState(20000);
  const [showTemp, setShowTemp]                 = useState(true);
  const [showLevel, setShowLevel]               = useState(true);
  const [chartTab, setChartTab]                 = useState('live');
  const [isOnline, setIsOnline]                 = useState(false);
  const timerRef = useRef(null);

  /* Derived */
  const tankH = selectedNodeData?.tank_height_cm || 100;
  const tankD = selectedNodeData?.tank_length_cm || 50;  // diameter stored in tank_length_cm
  const tankR = tankD / 2;
  const latest       = sensorData[0] || null;
  const temperature  = latest?.temperature || 0;
  const waterLevelCm = Math.max(0, latest?.water_level || 0);
  const waterPercent = Math.min(100, Math.round((waterLevelCm / tankH) * 100));
  // Cylindrical volume: π * r² * h  (cm³ → litres ÷ 1000)
  const volumeLitres   = (Math.PI * tankR * tankR * waterLevelCm / 1000).toFixed(0);
  const totalVolLitres = (Math.PI * tankR * tankR * tankH      / 1000).toFixed(0);

  /* Stats */
  const temps  = sensorData.map(d => d.temperature).filter(Boolean);
  const levels = sensorData.map(d => Math.max(0, d.water_level || 0));
  const tMin  = temps.length  ? Math.min(...temps).toFixed(1)  : '--';
  const tMax  = temps.length  ? Math.max(...temps).toFixed(1)  : '--';
  const tAvg  = temps.length  ? (temps.reduce((a,b)=>a+b,0)/temps.length).toFixed(1) : '--';
  const lMin  = levels.length ? Math.min(...levels).toFixed(1) : '--';
  const lMax  = levels.length ? Math.max(...levels).toFixed(1) : '--';
  const lAvg  = levels.length ? (levels.reduce((a,b)=>a+b,0)/levels.length).toFixed(1) : '--';

  /* Fill tag — no tag shown in KPI, just used for footer text */
  const fillFoot = waterPercent < 20 ? 'Critically low' :
                   waterPercent < 40 ? 'Refill soon'    :
                   waterPercent > 85 ? 'Nearly full'    : `${tankH} cm tank`;

  /* Time filter */
  const filterByTime = (data) => {
    if (timeRange === 'all') return data;
    const ms = {'1h':3600000,'6h':21600000,'24h':86400000,'7d':604800000}[timeRange]||Infinity;
    return data.filter(d => Date.now() - new Date(d.created_at) <= ms);
  };

  /* Chart data */
  const chartData = filterByTime([...sensorData].reverse()).map(item => ({
    time:        new Date(item.created_at).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit'}),
    temperature: Math.round(item.temperature * 10) / 10,
    waterLevel:  Math.max(0, parseFloat((item.water_level||0).toFixed(1))),
  }));

  /* Export */
  const doExp = (fmt) => {
    if (!fmt) return;
    const rows = chartData.map(d => ({time:d.time, temp:d.temperature, level:d.waterLevel}));
    if (fmt === 'json') {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([JSON.stringify(rows,null,2)],{type:'application/json'}));
      a.download = 'aquasense_data.json'; a.click();
    } else {
      let csv = 'Time,Temperature_C,WaterLevel_cm\n';
      rows.forEach(r => { csv += `${r.time},${r.temp},${r.level}\n`; });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
      a.download = 'aquasense_data.csv'; a.click();
    }
  };

  /* Fetch nodes */
  const API = process.env.REACT_APP_API_URL || 'http://127.0.0.1:8000';

  const fetchNodes = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/tank-parameters`);
      const data = res.data || [];
      setNodes(data);
      if (data.length > 0 && !selectedNode) {
        setSelectedNode(data[0].node_id);
        setSelectedNodeData(data[0]);
      }
    } catch(e) { console.error(e); }
  }, [selectedNode]);

  /* Fetch sensor data */
  const fetchSensorData = useCallback(async () => {
    if (!selectedNode) return;
    try {
      // Trigger backend to pull latest reading from ThingSpeak into DB
      await axios.get(`${API}/refresh?node_id=${selectedNode}`);
      // Now read the updated data from DB
      const res = await axios.get(`${API}/sensor-data?node_id=${selectedNode}`);
      const clean = (res.data || []).filter(d => d.water_level >= 0 && d.water_level <= 500);
      if (clean.length > 0) {
        setSensorData(clean); setHasData(true); setStatusMsg('');
        setLastUpdated(fsh(ist())); setIsOnline(true);
        const dot = document.getElementById('ldot');
        const ltx = document.getElementById('ltx');
        if (dot) dot.className = 'ld on';
        if (ltx) ltx.textContent = 'Live';
      } else {
        setHasData(false); setIsOnline(false);
        setStatusMsg(`No sensor data for ${selectedNode}`);
        const dot = document.getElementById('ldot');
        if (dot) dot.className = 'ld off';
      }
    } catch(e) {
      setIsOnline(false);
      setStatusMsg('Connection error. Check backend.');
      const dot = document.getElementById('ldot');
      if (dot) dot.className = 'ld off';
    } finally { setLoading(false); }
  }, [selectedNode]);

  useEffect(() => { fetchNodes(); }, []);
  useEffect(() => { if (selectedNode) { setLoading(true); fetchSensorData(); } }, [selectedNode]);
  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = setInterval(fetchSensorData, refreshMs);
    return () => clearInterval(timerRef.current);
  }, [fetchSensorData, refreshMs]);

  const handleNodeChange = (nodeId) => {
    setSelectedNode(nodeId);
    setSelectedNodeData(nodes.find(n => n.node_id === nodeId) || null);
    setSensorData([]); setLoading(true);
  };

  /* Inject controls into navbar */
  useEffect(() => {
    setNavControls(
      <div className="nav-controls-inner">
        <select className="ctrl-sel" value={selectedNode} onChange={e => handleNodeChange(e.target.value)}>
          {nodes.length === 0 && <option value="">No nodes</option>}
          {nodes.map(n => (
            <option key={n.node_id} value={n.node_id}>{n.node_id} ({n.tank_height_cm}cm)</option>
          ))}
        </select>
        <select className="ctrl-sel" value={timeRange} onChange={e => setTimeRange(e.target.value)}>
          <option value="all">All Time</option>
          <option value="1h">Last 1h</option>
          <option value="6h">Last 6h</option>
          <option value="24h">Last 24h</option>
          <option value="7d">Last 7d</option>
        </select>
        <select className="ctrl-sel" value={refreshMs} onChange={e => setRefreshMs(Number(e.target.value))}>
          <option value={5000}>Refresh: 5s</option>
          <option value={10000}>Refresh: 10s</option>
          <option value={20000}>Refresh: 20s</option>
          <option value={60000}>Refresh: 1 min</option>
        </select>
        <select className="ctrl-sel" defaultValue="" onChange={e => { if(e.target.value) doExp(e.target.value); e.target.value=''; }}>
          <option value="" disabled>Export</option>
          <option value="json">JSON</option>
          <option value="csv">CSV</option>
        </select>
      </div>
    );
  }, [nodes, selectedNode, timeRange, refreshMs, chartData]);

  /* Tooltip */
  const CustomTooltip = ({ active, payload, label }) => {
    if (!active || !payload || !payload.length) return null;
    return (
      <div className="chart-tooltip">
        <div className="ct-label">{label}</div>
        {payload.map((p, i) => (
          <div key={i} className="ct-row" style={{ color: p.color }}>
            {p.name === 'temperature' ? `Temp: ${p.value}°C` : `Level: ${p.value} cm`}
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="grid">


      {/* KPI 1 Temperature */}
      <div className="kp k1">
        <div className="kp-bar"></div>
        <div className="kp-r">
          <div className="kp-lb">Temperature</div>
        </div>
        <div className="kp-v">
          <span>{loading ? '--' : (!hasData ? 'N/A' : temperature.toFixed(1))}</span>
          <span className="kp-u">°C</span>
        </div>
      </div>

      {/* KPI 2 Water Level */}
      <div className="kp k2">
        <div className="kp-bar"></div>
        <div className="kp-r">
          <div className="kp-lb">Water Level</div>
        </div>
        <div className="kp-v">
          <span>{loading ? '--' : (!hasData ? 'N/A' : waterLevelCm.toFixed(1))}</span>
          <span className="kp-u">cm</span>
        </div>
      </div>

      {/* Volume KPI */}
      <div className="kp gv">
        <div className="kp-bar"></div>
        <div className="kp-r">
          <div className="kp-lb">Volume</div>
        </div>
        <div className="kp-v">
          <span>{loading||!hasData?'--':volumeLitres}</span>
          <span className="kp-u"> L</span>
        </div>
      </div>

      {/* KPI 3 Tank Fill */}
      <div className="kp k3">
        <div className="kp-bar"></div>
        <div className="kp-r">
          <div className="kp-lb">Tank Fill</div>
        </div>
        <div className="kp-v">
          <span>{loading ? '--' : (!hasData ? 'N/A' : waterPercent)}</span>
          <span className="kp-u">%</span>
        </div>
      </div>

      {/* KPI 4 Status */}
      <div className="kp k4">
        <div className="kp-bar"></div>
        <div className="kp-r">
          <div className="kp-lb">Status</div>
        </div>
        <div className="kp-v kp-v-status" style={{ color: isOnline ? 'var(--gn)' : 'var(--pk)' }}>
          {isOnline ? 'Online' : 'Offline'}
        </div>
      </div>

      {/* Map Panel */}
      <div className="pn gm">
        <div className="pn-hd">
          <div className="pn-ti">Deployment</div>
          {statusMsg && <div style={{fontSize:9,color:'var(--or)'}}>{statusMsg}</div>}
        </div>
        <div className="mw">
          <iframe
            title="map"
            src="https://www.openstreetmap.org/export/embed.html?bbox=73.828%2C18.512%2C73.838%2C18.522&layer=mapnik&marker=18.5165%2C73.8330"
            loading="lazy"
          />
        </div>
        <div className="mft">
          <div className="mfi"><b>Facility:</b> The Poona Lodge</div>
          <div className="mfi"><b>Area:</b> FC Road, Deccan Gymkhana</div>
          <div className="mfi"><b>City:</b> Pune, Maharashtra</div>
        </div>
      </div>

      {/* Chart Panel */}
      <div className="pn gc">
        <div className="pn-hd">
          <div className="pn-ti">Sensor Data</div>
          <div className="pn-hr">
            {/* Temp toggle */}
            <button
              className={`t2 ${showTemp ? 'sel-temp' : ''}`}
              onClick={() => setShowTemp(v => !v)}
            >
              Temp
            </button>
            {/* Level toggle */}
            <button
              className={`t2 ${showLevel ? 'sel-level' : ''}`}
              onClick={() => setShowLevel(v => !v)}
            >
              Level
            </button>
            <span className="sep"></span>
            {/* Chart time tabs */}
            <button className={`t2 ${chartTab==='live' ?'on':''}`} onClick={()=>setChartTab('live')}>Live</button>
            <button className={`t2 ${chartTab==='day'  ?'on':''}`} onClick={()=>setChartTab('day')}>24h</button>
            <button className={`t2 ${chartTab==='week' ?'on':''}`} onClick={()=>setChartTab('week')}>7d</button>
            <button className={`t2 ${chartTab==='month'?'on':''}`} onClick={()=>setChartTab('month')}>30d</button>
          </div>
        </div>
        <div className="pn-bd">
          {loading && sensorData.length === 0 ? (
            <div className="no-data-msg">Loading sensor data…</div>
          ) : !hasData ? (
            <div className="no-data-msg">No data for selected node</div>
          ) : !showTemp && !showLevel ? (
            <div className="no-data-msg">Select Temp and/or Level to display</div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top:4, right:14, bottom:4, left:0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--gc)" strokeWidth={0.4} />
                <XAxis
                  dataKey="time"
                  tick={{ fontSize:8, fill:'var(--tx3)', fontFamily:"'IBM Plex Mono',monospace" }}
                  tickLine={false} interval="preserveStartEnd"
                />
                {showTemp && (
                  <YAxis yAxisId="temp" orientation="left"
                    tick={{ fontSize:9, fill:'var(--cy)', fontFamily:"'IBM Plex Mono',monospace" }}
                    tickLine={false} tickFormatter={v=>`${v.toFixed(1)}°C`} width={42}
                  />
                )}
                {showLevel && (
                  <YAxis yAxisId="level" orientation="right"
                    tick={{ fontSize:9, fill:'var(--bl)', fontFamily:"'IBM Plex Mono',monospace" }}
                    tickLine={false} tickFormatter={v=>`${v.toFixed(0)}cm`} width={38}
                  />
                )}
                <Tooltip content={<CustomTooltip />} />
                {showTemp && (
                  <Line yAxisId="temp" type="monotone" dataKey="temperature"
                    stroke="var(--cy)" strokeWidth={2} dot={false}
                    name="temperature" activeDot={{ r:4 }}
                  />
                )}
                {showLevel && (
                  <Line yAxisId="level" type="monotone" dataKey="waterLevel"
                    stroke="var(--bl)" strokeWidth={2} dot={false}
                    name="waterLevel" activeDot={{ r:4 }}
                  />
                )}
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
        {/* Stats bar */}
        <div className="sb">
          <div className="st"><div className="sd" style={{background:'var(--cy)'}}></div><div className="sl">T.Min</div><div className="sv" style={{color:'var(--cy)'}}>{tMin}°C</div></div>
          <div className="st"><div className="sd" style={{background:'var(--pk)'}}></div><div className="sl">T.Max</div><div className="sv" style={{color:'var(--pk)'}}>{tMax}°C</div></div>
          <div className="st"><div className="sd" style={{background:'var(--cy)'}}></div><div className="sl">T.Avg</div><div className="sv" style={{color:'var(--cy)'}}>{tAvg}°C</div></div>
          <div className="st"><div className="sd" style={{background:'var(--bl)'}}></div><div className="sl">L.Min</div><div className="sv" style={{color:'var(--bl)'}}>{lMin} cm</div></div>
          <div className="st"><div className="sd" style={{background:'var(--or)'}}></div><div className="sl">L.Max</div><div className="sv" style={{color:'var(--or)'}}>{lMax} cm</div></div>
          <div className="st"><div className="sd" style={{background:'var(--bl)'}}></div><div className="sl">L.Avg</div><div className="sv" style={{color:'var(--bl)'}}>{lAvg} cm</div></div>
          <div className="st"><div className="sd" style={{background:'var(--gn)'}}></div><div className="sl">Pts</div><div className="sv" style={{color:'var(--gn)'}}>{chartData.length}</div></div>
        </div>
      </div>



    </div>
  );
};

export default Home;