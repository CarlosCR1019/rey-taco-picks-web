import { useState, useEffect } from 'react'
import './App.css'

function App() {
  const [picks, setPicks] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // En producción, esto podría ser una llamada a una API real
    // Por ahora, leemos el JSON generado por el bot de Python
    fetch('/picks.json')
      .then(res => res.json())
      .then(data => {
        setPicks(data)
        setLoading(false)
      })
      .catch(err => {
        console.error("Error cargando los picks:", err)
        setLoading(false)
      })
  }, [])

  return (
    <div className="app-container">
      <header className="header">
        <div className="logo-container">
          <h1>Rey Taco <span className="logo-accent">Picks</span></h1>
        </div>
        <div className="premium-badge">
          Acceso Premium
        </div>
      </header>

      <main>
        <section className="hero">
          <h2>Gana con Inteligencia Artificial</h2>
          <p>Análisis predictivo de alto rendimiento para identificar las mejores cuotas del mercado antes de que las líneas se muevan.</p>
        </section>

        <section className="picks-section">
          <h3>
            <span className="live-indicator"></span> 
            Picks del Día
          </h3>
          
          {loading ? (
            <div className="loading">Analizando el mercado...</div>
          ) : (
            <div className="picks-grid">
              {picks.map((pick) => (
                <div key={pick.id} className="pick-card">
                  
                  <div className="card-header">
                    <span className="sport-tag">{pick.deporte}</span>
                    <span className="confidence-score">Respaldo de datos: {pick.confianza}</span>
                  </div>
                  
                  <div className="card-body">
                    <h4>{pick.partido}</h4>
                    <div className="the-pick">
                      <span className="pick-text">{pick.pick}</span>
                      <span className="pick-odds">{pick.cuota}</span>
                    </div>
                  </div>
                  
                  <div className="card-footer">
                    <p><strong>Razonamiento IA:</strong> {pick.razonamiento}</p>
                  </div>
                  
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  )
}

export default App
