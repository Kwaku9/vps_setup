import '@fontsource-variable/public-sans';
import '@fontsource/jetbrains-mono/400.css';
import '@fontsource/jetbrains-mono/500.css';
import './app.css';
import { mount } from 'svelte';
import App from './App.svelte';

mount(App, { target: document.getElementById('app')! });

if ('serviceWorker' in navigator && location.protocol === 'https:') {
  navigator.serviceWorker.register('/m/sw.js', { scope: '/m/' }).catch(() => {});
}
