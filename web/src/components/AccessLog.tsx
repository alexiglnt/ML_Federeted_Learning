/* Who has opened the files on this project.
 *
 * Shown to contributors, not just to the owner — that is the point of it. The
 * platform asks researchers to hand over unpublished measurements and tells
 * them the owner can read those files; the counterpart is a record of when
 * that actually happened, visible to the person whose data it is.
 *
 * A contributor sees reads of their own files only. The owner sees all of
 * them. The endpoint decides that, not this component.
 */

import type { AccessLogEntry } from "../lib/api";

export default function AccessLog({
  entries,
  isOwner,
}: {
  entries: AccessLogEntry[];
  isOwner: boolean;
}) {
  if (entries.length === 0) {
    return (
      <p className="muted">
        {isOwner
          ? "No file on this project has been downloaded yet. Every download you make is recorded here and is visible to the contributor whose file it is."
          : "Nobody has downloaded your file. If the owner does, it appears here."}
      </p>
    );
  }

  return (
    <>
      <p className="muted">
        {isOwner
          ? "Every download of a contributed file. The contributor sees the entries for their own file."
          : "Every time one of your files was opened."}
      </p>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">When</th>
              <th scope="col">Who</th>
              <th scope="col">File</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry, index) => (
              <tr key={`${entry.at}-${index}`}>
                <td className="small">{new Date(entry.at).toLocaleString()}</td>
                <td>
                  {entry.actor_name}
                  {entry.detail?.by_owner && (
                    <span className="badge"> project owner</span>
                  )}
                </td>
                <td className="small">{entry.detail?.filename ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
