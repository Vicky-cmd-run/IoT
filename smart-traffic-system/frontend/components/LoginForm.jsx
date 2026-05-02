import { useState } from "react";

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
      <section className="panel auth-panel simple-auth-panel">
        <div className="auth-header">
          <h1>Traffic Control Login</h1>
          <p className="subtle-text">
            Sign in to access live monitoring, ingestion, and routing controls.
          </p>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="field-label" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            className="text-input"
            onChange={(event) => setEmail(event.target.value)}
            type="email"
            value={email}
          />

          <label className="field-label" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            className="text-input"
            onChange={(event) => setPassword(event.target.value)}
            type="password"
            value={password}
          />

          <button className="primary-button auth-submit" disabled={loading} type="submit">
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>

        <div className="status-banner compact-banner">{status}</div>
      </section>
    </main>
  );
}
