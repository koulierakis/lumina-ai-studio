import React, { useState } from 'react';
import './styles.css';

function App() {
  const [message, setMessage] = useState('Hello, Lumina Builder Test!');

  const handleClick = () => {
    setMessage('Button clicked!');
  };

  return (
    <div className='App'>
      <h1>Lumina Builder Test</h1>
      <button onClick={handleClick}>{message}</button>
    </div>
  );
}

export default App;