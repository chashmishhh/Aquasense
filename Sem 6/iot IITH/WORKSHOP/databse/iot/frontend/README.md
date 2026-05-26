# IOT Dashboard

A React-based dashboard for monitoring IoT sensors including water levels and temperature readings.

## Features

- **Navbar** with logo, title, notifications, and hamburger menu
- **Sidebar** with navigation between Home and Node Creation pages  
- **Home Page** featuring:
  - Two cards displaying real-time water level and temperature values
  - Interactive graphs showing 24-hour trends for both metrics
- **Node Creation Page** with form to create new sensor nodes

## Installation

1. Make sure you have Node.js installed
2. Install dependencies:
   ```bash
   npm install
   ```

## Running the Application

1. Start the development server:
   ```bash
   npm start
   ```

2. Open [http://localhost:3000](http://localhost:3000) to view in browser

## API Integration

The Node Creation page integrates with a backend API:
- **Endpoint**: `http://127.0.0.1:8000/api/v1/tank-sensorparameters`
- **Method**: POST
- **Payload**: Tank sensor configuration including dimensions and GPS coordinates

Make sure your backend server is running on the specified endpoint for full functionality.

## Project Structure

```
src/
├── components/
│   ├── Navbar.js          # Top navigation bar
│   └── Sidebar.js         # Side navigation menu
├── pages/
│   ├── Home.js           # Dashboard with cards and graphs
│   └── NodeCreation.js   # Sensor node creation form
├── App.js                # Main application component
├── App.css               # Global styles
└── index.js              # Application entry point
```

## Dependencies

- React 18.2.0
- React Router DOM 6.3.0
- Recharts 2.5.0 (for graphs)
- Axios 1.4.0 (for API calls)