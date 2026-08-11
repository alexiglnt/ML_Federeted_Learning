/* Bascule clair/sombre. Le choix persiste dans localStorage ; le thème par
 * défaut est clair, quel que soit le réglage du système d'exploitation. Le
 * script anti-flash dans index.html applique déjà le sombre au premier
 * rendu si c'était le dernier choix : ce module ne fait que réagir au clic
 * et tenir le bouton à jour.
 */
const STORAGE_KEY = "deam-theme";

function apply(theme) {
  if (theme === "dark") document.documentElement.setAttribute("data-theme", "dark");
  else document.documentElement.removeAttribute("data-theme");

  const button = document.getElementById("theme-toggle");
  if (!button) return;
  const toDark = theme !== "dark";
  button.setAttribute("aria-pressed", String(theme === "dark"));
  button.querySelector(".theme-toggle-icon").textContent = toDark ? "🌙" : "☀️";
  button.querySelector(".theme-toggle-label").textContent =
    toDark ? "Dark mode" : "Light mode";
}

export function wireThemeToggle() {
  const current = localStorage.getItem(STORAGE_KEY) === "dark" ? "dark" : "light";
  apply(current);

  document.getElementById("theme-toggle")?.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "dark"
      ? "light" : "dark";
    localStorage.setItem(STORAGE_KEY, next);
    apply(next);
  });
}
