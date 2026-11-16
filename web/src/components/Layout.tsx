import { useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "../lib/auth";
import { currentTheme, toggleTheme, type Theme } from "../lib/theme";
import NotificationBell from "./NotificationBell";

/* Sun / moon and the doc-button's page icon are drawn at the same 18x18 size
 * and stroke weight as NotificationBell's bell, so all three header icon
 * buttons read as one family rather than a mismatched row. */
function SunIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="1.6" />
      <path
        d="M12 2.5v2.2M12 19.3v2.2M4.2 4.2l1.55 1.55M18.25 18.25l1.55 1.55M2.5 12h2.2M19.3 12h2.2M4.2 19.8l1.55-1.55M18.25 5.75l1.55-1.55"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M20 14.7A8.5 8.5 0 1 1 9.3 4a7 7 0 0 0 10.7 10.7Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ThemeToggle() {
  const [theme, setThemeState] = useState<Theme>(() => currentTheme());
  return (
    <button
      type="button"
      className="ghost icon-button"
      aria-pressed={theme === "dark"}
      onClick={() => setThemeState(toggleTheme())}
    >
      {theme === "dark" ? <SunIcon /> : <MoonIcon />}
      <span className="visually-hidden">
        Switch to {theme === "dark" ? "light" : "dark"} theme
      </span>
    </button>
  );
}

function DocIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M7 3.5h7l4 4V19a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 19V5A1.5 1.5 0 0 1 7 3.5Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M14 3.5V7a1 1 0 0 0 1 1h3.5" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M9 12.2h6M9 15.6h6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

function DocsButton() {
  return (
    <Link to="/docs" className="ghost button-like icon-button" title="Guide">
      <DocIcon />
      <span className="visually-hidden">Guide — how this site works</span>
    </Link>
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
            <DocsButton />
            {/* Nothing account-related renders until /auth/me settles, so the
                header does not flicker from signed-out to signed-in. */}
            {!loading &&
              (user ? (
                <>
                  <NotificationBell />
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
