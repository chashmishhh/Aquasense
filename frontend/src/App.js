import React, { useState, createContext, useContext } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import Sidebar from './components/Sidebar';
import Home from './pages/Home';
import NodeCreation from './pages/NodeCreation';
import './App.css';

export const ThemeContext = createContext();
export const useTheme = () => useContext(ThemeContext);

export const NavControlsContext = createContext();
export const useNavControls = () => useContext(NavControlsContext);

function App() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [darkMode, setDarkMode] = useState(true);
  const [navControls, setNavControls] = useState(null);

  return (
    <ThemeContext.Provider value={{ darkMode, toggleTheme: () => setDarkMode(d => !d) }}>
      <NavControlsContext.Provider value={{ setNavControls }}>
        <div className={`App ${darkMode ? 'dark' : 'light'}`}>
          <Router>
            <Navbar
              onToggleSidebar={() => setSidebarOpen(s => !s)}
              controls={navControls}
            />
            <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />
            <main className={`main-content ${sidebarOpen ? 'sidebar-open' : ''}`}>
              <Routes>
                <Route path="/" element={<Home />} />
                <Route path="/node-creation" element={<NodeCreation />} />
              </Routes>
            </main>
            <div className="ftr">
              <div className="fl"><span>Smart Water Level Monitoring</span> © 2026</div>
              <div className="fc">Samiksha Nalawade &amp; Rajlakshmi Desai</div>
              <div className="fr">AquaSense v6.0</div>
            </div>
          </Router>
        </div>
      </NavControlsContext.Provider>
    </ThemeContext.Provider>
  );
}

export default App;