import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useAuth } from "../lib/auth";

export default function Register() {
  const { signUp } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    email: "",
    password: "",
    full_name: "",
    institution: "",
    country: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function update(field: keyof typeof form) {
    return (event: React.ChangeEvent<HTMLInputElement>) =>
      setForm((current) => ({ ...current, [field]: event.target.value }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signUp({
        email: form.email,
        password: form.password,
        full_name: form.full_name,
        institution: form.institution || undefined,
        country: form.country || undefined,
      });
      navigate("/me");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Registration failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="narrow">
      <h1>Create an account</h1>
      <p className="muted">
        Your name and institution are shown alongside any contribution you make,
        so that the data you provide can be credited to you.
      </p>

      <form className="form" onSubmit={submit} noValidate>
        <label htmlFor="full_name">Full name</label>
        <input id="full_name" required value={form.full_name} onChange={update("full_name")} />

        <label htmlFor="email">Email address</label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          required
          value={form.email}
          onChange={update("email")}
        />

        <label htmlFor="password">
          Password <span className="hint">at least 10 characters</span>
        </label>
        <input
          id="password"
          type="password"
          autoComplete="new-password"
          required
          minLength={10}
          value={form.password}
          onChange={update("password")}
        />

        <label htmlFor="institution">
          Institution or company <span className="hint">optional</span>
        </label>
        <input id="institution" value={form.institution} onChange={update("institution")} />

        <label htmlFor="country">
          Country <span className="hint">optional</span>
        </label>
        <input id="country" value={form.country} onChange={update("country")} />

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Creating…" : "Create account"}
        </button>
      </form>

      <p className="muted">
        Already registered? <Link to="/login">Sign in</Link>.
      </p>
    </section>
  );
}
