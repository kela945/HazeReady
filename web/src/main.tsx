import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import Shell from './Shell'
import Console from './pages/Console'
import Monitor from './pages/Monitor'
import Report from './pages/Report'
import './index.css'

const router = createBrowserRouter([
  {
    path: '/',
    element: <Shell />,
    children: [
      { index: true, element: <Console /> },
      { path: 'monitor', element: <Monitor /> },
      { path: 'report', element: <Report /> },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
