import React from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.jsx';
import PublicStorefront from './PublicStorefront.jsx';
import './style.css';
const storefront = /^\/store\/([a-f0-9]{32})\/?$/.exec(window.location.pathname);
createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {storefront ? <PublicStorefront slug={storefront[1]} /> : <App />}
  </React.StrictMode>
);
