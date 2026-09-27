import React, { useState } from 'react';
import './App.css';

function App() {
  const [message, setMessage] = useState('Click the button!');

  const handleClick = () => {
    setMessage('Button clicked!');
  };

  return (
    <div className="App">
      <h1>Lumina Builder Test</h1>
      <button onClick={handleClick}>{message}</button>
    </div>
  );
}

export default App;