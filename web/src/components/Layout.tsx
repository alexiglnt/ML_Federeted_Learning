import { useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "../lib/auth";
import { currentTheme, toggleTheme, type Theme } from "../lib/theme";

function ThemeToggle() {
  const [theme, setThemeState] = useState<Theme>(() => currentTheme());
  return (
    <button
      type="button"
      className="ghost"
      aria-pressed={theme === "dark"}
      onClick={() => setThemeState(toggleTheme())}
    >
      <span aria-hidden="true">{theme === "dark" ? "☀" : "☾"}</span>
      <span className="visually-hidden">
        Switch to {theme === "dark" ? "light" : "dark"} theme
      </span>
    </button>
  );
}

export default function Layout() {
  const { user, loading, signOut } = useAuth();
  const navigate = useNavigate();

  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>

      <header className="site-header">
        <div className="wrap header-inner">
          <Link to="/" className="brand">
            <strong>Machining models</strong>
            <span className="brand-sub">pooled measurements, shared models</span>
          </Link>

          <nav className="site-nav" aria-label="Main">
            <NavLink to="/projects">Projects</NavLink>
            <NavLink to="/variables">Variables</NavLink>
            {user && <NavLink to="/me">My work</NavLink>}
          </nav>

          <div className="header-actions">
            <ThemeToggle />
            {/* Nothing account-related renders until /auth/me settles, so the
                header does not flicker from signed-out to signed-in. */}
            {!loading &&
              (user ? (
                <>
                  <Link to="/me" className="who">
                    {user.full_name}
                  </Link>
                  <button
                    type="button"
                    className="ghost"
                    onClick={async () => {
                      await signOut();
                      navigate("/");
                    }}
                  >
                    Sign out
                  </button>
                </>
              ) : (
                <>
                  <Link to="/login" className="ghost button-like">
                    Sign in
                  </Link>
                  <Link to="/register" className="primary button-like">
                    Create account
                  </Link>
                </>
              ))}
          </div>
        </div>
      </header>

      <main id="main" className="wrap">
        <Outlet />
      </main>

      <footer className="site-footer">
        <div className="wrap">
          <p>
            A research tool. Models published here carry no warranty and are not
            intended for production machining decisions.
          </p>
          <p className="muted">
            Under construction — see <code>ROADMAP.md</code> for what is not yet
            built and what must happen before this goes online.
          </p>
        </div>
      </footer>
    </>
  );
}
