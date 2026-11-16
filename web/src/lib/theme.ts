/* Light/dark toggle, persisted.
 *
 * The initial attribute is set by an inline script in index.html, before the
 * stylesheet loads, so a returning dark-theme visitor never sees a flash of
 * light. This module only handles changes made after that.
 */

const STORAGE_KEY = "mlfl-theme";

export type Theme = "light" | "dark";

export function currentTheme(): Theme {
  return document.documentElement.getAttribute("data-theme") === "dark"
    ? "dark"
    : "light";
}

export function setTheme(theme: Theme): void {
  if (theme === "dark") {
    document.documentElement.setAttribute("data-theme", "dark");
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* Private browsing can refuse storage; the toggle still works for this
       page view, it just will not be remembered. */
  }
}

export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === "dark" ? "light" : "dark";
  setTheme(next);
  return next;
}
