import React, { useState } from 'react';
import ReactDOM from 'react-dom/client';

function App() {
  const [message, setMessage] = useState('Hello, Lumina Builder Test!');

  const handleClick = () => {
    setMessage('Button clicked!');
  };

  return (
    <div style={{ textAlign: 'center', marginTop: '50px' }}>
      <h1>Lumina Builder Test</h1>
      <button onClickBroken={handleClick}>Click Me</button>
      <p>{message}</p>
    </div>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<App />);