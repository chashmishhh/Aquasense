import React from 'react';
import { useNavigate, useLocation } from 'react-router-dom';

const Sidebar = ({ isOpen, onClose }) => {
  const navigate = useNavigate();
  const location = useLocation();
  const go = (path) => { navigate(path); onClose(); };

  return (
    <>
      {isOpen && <div className="sidebar-overlay" onClick={onClose}></div>}
      <div className={`sidebar ${isOpen ? 'sidebar-open' : ''}`}>
        <div className="sidebar-header">
          <h3>Menu</h3>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>
        <nav className="sidebar-nav">
          <button className={`sidebar-btn ${location.pathname === '/' ? 'active' : ''}`} onClick={() => go('/')}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>
              <polyline points="9,22 9,12 15,12 15,22"/>
            </svg>
            Dashboard
          </button>
          <button className={`sidebar-btn ${location.pathname === '/node-creation' ? 'active' : ''}`} onClick={() => go('/node-creation')}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="3"/>
              <path d="M12 1v6m0 6v6m11-7h-6m-6 0H1"/>
            </svg>
            Node Creation
          </button>
        </nav>
        <div className="sidebar-footer">
          <div className="sidebar-info">
            <span>AquaSense v6.0</span>
            <span>© 2026 Samiksha &amp; Rajlakshmi</span>
          </div>
        </div>
      </div>
    </>
  );
};

export default Sidebar;