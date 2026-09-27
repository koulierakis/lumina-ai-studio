import React, { useState } from 'react';
import ReactDOM from 'react-dom/client';

const App = () => {
  const [message, setMessage] = useState('Click the button!');

  const handleClick = () => {
    setMessage('Button clicked!');
  };

  return (
    <div style={{ textAlign: 'center', marginTop: '50px' }}>
      <h1>Lumina Builder Test</h1>
      <button onClick={handleClick}>{message}</button>
    </div>
  );
};

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);