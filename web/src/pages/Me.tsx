import { useEffect, useState } from "react";

import { health, type HealthReport } from "../lib/api";
import { useAuth } from "../lib/auth";

export default function Me() {
  const { user } = useAuth();
  const [report, setReport] = useState<HealthReport | null>(null);

  useEffect(() => {
    health()
      .then(setReport)
      .catch(() => setReport(null));
  }, []);

  if (!user) return null;

  return (
    <section>
      <h1>My work</h1>
      <dl className="key-values">
        <dt>Name</dt>
        <dd>{user.full_name}</dd>
        <dt>Email</dt>
        <dd>{user.email}</dd>
        <dt>Institution</dt>
        <dd>{user.institution ?? "—"}</dd>
        <dt>Role</dt>
        <dd>{user.role}</dd>
      </dl>

      <div className="notice">
        <h2>Not built yet</h2>
        <p>
          This will list the projects you own, the contributions you have made,
          the models you have access to, and any contributions awaiting your
          review. Project creation is lot 1 of the build.
        </p>
      </div>

      {report && (
        <p className="muted small">
          Server: {report.environment} · database {report.database} · front end{" "}
          {report.front_end_built ? "built" : "served by Vite"}
        </p>
      )}
    </section>
  );
}
