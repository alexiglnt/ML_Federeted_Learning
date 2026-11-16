import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <section className="narrow">
      <h1>Page not found</h1>
      <p className="muted">
        Nothing lives at this address. It may be a part of the site that has not
        been built yet — see <code>ROADMAP.md</code>.
      </p>
      <p>
        <Link to="/">Back to the home page</Link>
      </p>
    </section>
  );
}
