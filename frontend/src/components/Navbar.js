import React, { useState, useEffect } from 'react';
import { useTheme } from '../App';

const SunIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="5"/>
    <line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/>
    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
    <line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/>
    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
  </svg>
);
const MoonIcon = () => (
  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
  </svg>
);
const WaterIcon = () => (
  <svg viewBox="0 0 24 24" width="13" height="13" fill="currentColor">
    <path d="M12 2.69l5.66 5.66a8 8 0 1 1-11.31 0z"/>
  </svg>
);

const Navbar = ({ onToggleSidebar, controls }) => {
  const { darkMode, toggleTheme } = useTheme();
  const [time, setTime] = useState('--:--:--');

  useEffect(() => {
    const tick = () => {
      const n = new Date();
      const ist = new Date(n.getTime() + n.getTimezoneOffset() * 60000 + 5.5 * 3600000);
      const h = ist.getHours(), m = ist.getMinutes(), s = ist.getSeconds();
      const ampm = h >= 12 ? 'PM' : 'AM';
      const hh = (h % 12 || 12).toString().padStart(2, '0');
      setTime(`${hh}:${m.toString().padStart(2,'0')}:${s.toString().padStart(2,'0')} ${ampm}`);
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="top">
      <div className="tl">
        <button className="hamburger-btn" onClick={onToggleSidebar}>
          <div className="hamburger-line"></div>
          <div className="hamburger-line"></div>
          <div className="hamburger-line"></div>
        </button>
        <div className="tico"><WaterIcon /></div>
        <div className="tnm">AquaSense</div>
        <span className="tsp">|</span>
        {/* Controls passed from Home page */}
        {controls && <div className="nav-controls">{controls}</div>}
      </div>
      <div className="tr">
        
        <button
          className="cb"
          onClick={toggleTheme}
          title={darkMode ? 'Switch to Light' : 'Switch to Dark'}
          style={{ color: darkMode ? '#f0c040' : 'var(--tx2)' }}
        >
          {darkMode ? <SunIcon /> : <MoonIcon />}
        </button>
        <div className="ck">{time}</div>
      </div>
    </div>
  );
};

export default Navbar;