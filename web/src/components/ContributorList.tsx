/* Who the model is made of.
 *
 * Public, and that is deliberate: this is the scientific credit for handing
 * over measurements that cost machine time to produce, and besides model
 * access it is most of what a contributor gets back. What stays private is the
 * file — never the fact of having contributed.
 *
 * Only accepted contributions appear. A pending one is a claim the owner has
 * not agreed to yet, and listing it would advertise it as though they had.
 */

import type { ContributorOut } from "../lib/api";

export default function ContributorList({ contributors }: { contributors: ContributorOut[] }) {
  if (contributors.length === 0) {
    return (
      <p className="muted">
        No accepted contributions yet. The first one to add measurements here
        will be credited on this page.
      </p>
    );
  }

  const labs = new Set(contributors.map((item) => item.institution ?? item.name)).size;
  const rows = contributors.reduce((total, item) => total + item.n_rows, 0);

  return (
    <>
      <p className="muted">
        {rows} rows from {contributors.length} contribution
        {contributors.length === 1 ? "" : "s"}
        {labs > 1 && `, across ${labs} institutions`}. Cite them if you use this
        model.
      </p>
      <ul className="contributor-list">
        {contributors.map((item, index) => (
          <li key={`${item.name}-${item.contributed_at}-${index}`} className="contributor">
            <div>
              <strong>{item.name}</strong>
              {item.institution && <span className="muted"> · {item.institution}</span>}
            </div>
            <p className="meta-line small">
              <span>{item.n_rows} rows</span>
              {item.measurement_method && <span>{item.measurement_method}</span>}
              <span>{new Date(item.contributed_at).toLocaleDateString()}</span>
              {/* A federated contributor improved the reference model without
                  ever uploading a file. The credit is identical; saying how it
                  arrived is what makes that credible. */}
              {item.mode === "federated" && (
                <span className="badge">summary statistics only</span>
              )}
            </p>
          </li>
        ))}
      </ul>
    </>
  );
}
