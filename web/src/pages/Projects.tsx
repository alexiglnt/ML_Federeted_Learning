/** Discovery. Not built yet — this is lot 4 in ROADMAP.md.
 *
 * Left as an explicit placeholder rather than an empty route so that the
 * navigation is honest about what exists: the sequencing of this build was
 * "every finished lot leaves a working site", and a dead link would undercut
 * that.
 */
export default function Projects() {
  return (
    <section>
      <h1>Projects</h1>
      <div className="notice">
        <h2>Not built yet</h2>
        <p>
          Project discovery is lot 4 of the build. It will offer faceted
          filtering — target quantity, material, process, input variables, size —
          and a reverse search where you drop your own file first and projects
          are ranked by how well they match your columns and how much of your
          data falls inside their validity domain.
        </p>
        <p className="muted">
          See <code>ROADMAP.md</code> for the build order and what is done.
        </p>
      </div>
    </section>
  );
}
