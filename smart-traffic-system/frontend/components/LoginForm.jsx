import { useState } from "react";
import { Building2, Lock, Sparkles } from "lucide-react";

export default function LoginForm({ onLogin, status }) {
  const [email, setEmail] = useState("vigneshgnanasekaran8@gmail.com");
  const [password, setPassword] = useState("Viggu@2005");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setLoading(true);
    await onLogin({ email, password });
    setLoading(false);
  };

  return (
    <main className="app-shell auth-shell">
      <section className="panel auth-panel">
        <div className="eyebrow"><Sparkles size={14} /> FlowSync AI</div>
        <h1 className="hero-title">Sign in to the investor demo</h1>
        <p className="hero-text">
          A predictive mobility platform for cities, campuses, and high-density corridors.
          Use the secure demo login to show the digital twin, optimization engine, and route intelligence in action.
        </p>
        <div className="auth-proof">
          <div className="auth-proof-item">
            <Building2 size={16} />
            <span>Smart-city SaaS positioning</span>
          </div>
          <div className="auth-proof-item">
            <Lock size={16} />
            <span>Protected operations dashboard</span>
          </div>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            Email
            <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" />
          </label>
          <label>
            Password
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
            />
          </label>
          <button className="auth-button" disabled={loading} type="submit">
            {loading ? "Opening demo..." : "Enter dashboard"}
          </button>
        </form>

        <div className="status-pill">{status}</div>
      </section>
    </main>
  );
}
