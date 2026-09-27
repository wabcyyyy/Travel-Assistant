import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './react-app/App'
import './react-app/styles.css'

createRoot(document.getElementById('app')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
