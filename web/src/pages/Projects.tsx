/* Discovery.
 *
 * Two ways in, and "match my file" is placed first on purpose (ARCHITECTURE.md
 * §7). A researcher arriving here does not know which projects exist; they know
 * what they measured. Asking them to guess a search term for a project they
 * have never heard of is the wrong direction for the question, so the file drop
 * comes before the filters rather than being buried under them.
 *
 * Matching stores nothing. That is stated on the page, because "upload your
 * unpublished measurements to see if this is worth your time" is otherwise a
 * fair thing to be suspicious of.
 */

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import MatchCard from "../components/MatchCard";
import ProjectCard from "../components/ProjectCard";
import {
  projects as projectsApi,
  type Facets,
  type MatchFileResponse,
  type ProjectFilters,
  type ProjectSummary,
} from "../lib/api";
import { useAuth } from "../lib/auth";

/** One toggleable group of facet values. */
function ChipGroup({
  legend,
  hint,
  options,
  selected,
  onToggle,
}: {
  legend: string;
  hint?: string;
  options: { value: string; label: string; count: number }[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  if (options.length === 0) return null;
  return (
    <fieldset className="facet">
      <legend>
        {legend}
        {hint && <span className="hint"> {hint}</span>}
      </legend>
      <ul className="chip-list">
        {options.map((option) => {
          const on = selected.includes(option.value);
          return (
            <li key={option.value}>
              <button
                type="button"
                className={`chip toggle${on ? " on" : ""}`}
                aria-pressed={on}
                onClick={() => onToggle(option.value)}
              >
                {option.label}
                <span className="muted small"> {option.count}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}

export default function Projects() {
  const { user } = useAuth();
  const [rows, setRows] = useState<ProjectSummary[]>([]);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [filters, setFilters] = useState<ProjectFilters>({ sort: "recent" });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [matching, setMatching] = useState(false);
  const [match, setMatch] = useState<MatchFileResponse | null>(null);
  const [matchError, setMatchError] = useState<string | null>(null);

  useEffect(() => {
    projectsApi.facets().then(setFacets).catch(() => setFacets(null));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    // Debounced because the text box fires on every keystroke; the facet
    // toggles would be fine without it.
    const timer = setTimeout(() => {
      projectsApi
        .search(filters)
        .then((data) => {
          if (!cancelled) setRows(data);
        })
        .catch((caught: unknown) => {
          if (!cancelled)
            setError(caught instanceof Error ? caught.message : "Could not load.");
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [filters]);

  const toggle = useCallback((key: "material" | "process" | "input" | "target", value: string) => {
    setFilters((current) => {
      const list = current[key] ?? [];
      return {
        ...current,
        [key]: list.includes(value)
          ? list.filter((item) => item !== value)
          : [...list, value],
      };
    });
  }, []);

  async function runMatch(file: File) {
    setMatching(true);
    setMatchError(null);
    try {
      setMatch(await projectsApi.match(file));
    } catch (caught) {
      setMatch(null);
      setMatchError(caught instanceof Error ? caught.message : "Could not read that file.");
    } finally {
      setMatching(false);
    }
  }

  const activeFilters =
    (filters.material?.length ?? 0) +
    (filters.process?.length ?? 0) +
    (filters.input?.length ?? 0) +
    (filters.target?.length ?? 0) +
    (filters.min_rows ? 1 : 0) +
    (filters.has_model !== null && filters.has_model !== undefined ? 1 : 0);

  return (
    <section>
      <div className="page-head">
        <h1>Projects</h1>
        {user && (
          <Link to="/projects/new" className="primary button-like">
            Create a project
          </Link>
        )}
      </div>

      {/* Match my file ---------------------------------------------------- */}
      <div className="notice">
        <h2>Start from your file</h2>
        <p>
          Drop the measurements you already have. Your columns are read against
          the registry and projects are ranked by how well they fit — how many
          of your quantities they use, and how much of your data falls inside
          the range they have covered.
        </p>
        <p className="muted small">
          The file is read in memory and <strong>nothing is stored</strong> — no
          upload, no record, no trace. Checking whether contributing is worth
          your time should not require contributing first.
        </p>
        <input
          type="file"
          accept=".csv,.txt,.tsv,.xlsx,.xlsm"
          aria-label="Your measurements, for matching"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void runMatch(file);
          }}
        />
        {matching && <p className="muted">Reading…</p>}
        {matchError && (
          <p className="error" role="alert">
            {matchError}
          </p>
        )}
      </div>

      {match && (
        <>
          <div className="page-head">
            <h2>Projects that fit {match.filename}</h2>
            <button type="button" className="ghost" onClick={() => setMatch(null)}>
              Clear
            </button>
          </div>

          <p className="muted small">
            Read as {match.parse_report.n_rows} rows, {match.parse_report.n_columns}{" "}
            columns, decimal “{match.parse_report.decimal}”
            {match.parse_report.separator && `, separator “${match.parse_report.separator}”`}.
          </p>

          <h3>What your columns were read as</h3>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Your column</th>
                  <th scope="col">Read as</th>
                  <th scope="col">Match</th>
                  <th scope="col">Numbers</th>
                </tr>
              </thead>
              <tbody>
                {match.detected.map((item) => (
                  <tr key={item.column}>
                    <td>{item.column}</td>
                    <td>
                      <code className="small">{item.variable_key}</code>
                      {item.unit_conflict && (
                        <>
                          <br />
                          <span className="warn-text small">{item.unit_conflict}</span>
                        </>
                      )}
                    </td>
                    <td>
                      {item.exact ? (
                        <span className="badge">exact</span>
                      ) : (
                        <span className="badge warn">
                          approximate · {Math.round(item.confidence * 100)}%
                        </span>
                      )}
                    </td>
                    <td className="muted small">{item.n_values}</td>
                  </tr>
                ))}
                {match.unmatched_columns.map((column) => (
                  <tr key={column}>
                    <td>{column}</td>
                    <td className="muted">— nothing in the registry —</td>
                    <td>
                      <span className="muted small">no match</span>
                    </td>
                    <td className="muted small">—</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {match.unmatched_columns.length > 0 && (
            <p className="muted small">
              A heading nobody recognises may simply be a quantity the registry
              does not carry yet. You can{" "}
              <Link to="/variables">propose it</Link> and use it immediately.
            </p>
          )}

          <h3>Ranked projects</h3>
          {match.matches.length === 0 ? (
            <p className="muted">
              No project uses any of the quantities in this file. That is worth
              knowing in itself — it may be a project waiting to be created.
            </p>
          ) : (
            <ul className="project-list">
              {match.matches.map((entry) => (
                <MatchCard key={entry.project.id} match={entry} />
              ))}
            </ul>
          )}
        </>
      )}

      {/* Browse ----------------------------------------------------------- */}
      {!match && (
        <>
          <h2>Or browse</h2>

          <div className="field-row wide">
            <label htmlFor="q">Search</label>
            <input
              id="q"
              value={filters.q ?? ""}
              placeholder="titanium, turning, residual stress…"
              onChange={(event) =>
                setFilters((current) => ({ ...current, q: event.target.value }))
              }
            />
          </div>

          {facets && (
            <div className="facets">
              <ChipGroup
                legend="Material"
                options={facets.materials.map((item) => ({
                  value: item.value,
                  label: item.value,
                  count: item.count,
                }))}
                selected={filters.material ?? []}
                onToggle={(value) => toggle("material", value)}
              />
              <ChipGroup
                legend="Process"
                options={facets.processes.map((item) => ({
                  value: item.value,
                  label: item.value,
                  count: item.count,
                }))}
                selected={filters.process ?? []}
                onToggle={(value) => toggle("process", value)}
              />
              <ChipGroup
                legend="Predicts"
                hint="any of these"
                options={facets.targets.map((item) => ({
                  value: item.key,
                  label: item.display_name,
                  count: item.count,
                }))}
                selected={filters.target ?? []}
                onToggle={(value) => toggle("target", value)}
              />
              <ChipGroup
                legend="Uses these inputs"
                hint="all of them — projects you could contribute to"
                options={facets.inputs.map((item) => ({
                  value: item.key,
                  label: item.display_name,
                  count: item.count,
                }))}
                selected={filters.input ?? []}
                onToggle={(value) => toggle("input", value)}
              />

              <fieldset className="facet">
                <legend>Size and state</legend>
                <div className="predict-grid">
                  <div className="field-row">
                    <label htmlFor="min-rows">At least this many rows</label>
                    <input
                      id="min-rows"
                      type="number"
                      min={0}
                      step={1}
                      className="tiny"
                      value={filters.min_rows ?? ""}
                      onChange={(event) =>
                        setFilters((current) => ({
                          ...current,
                          min_rows: event.target.value ? Number(event.target.value) : null,
                        }))
                      }
                    />
                  </div>
                  <div className="field-row">
                    <label htmlFor="has-model">Model</label>
                    <select
                      id="has-model"
                      value={
                        filters.has_model === null || filters.has_model === undefined
                          ? ""
                          : String(filters.has_model)
                      }
                      onChange={(event) =>
                        setFilters((current) => ({
                          ...current,
                          has_model:
                            event.target.value === "" ? null : event.target.value === "true",
                        }))
                      }
                    >
                      <option value="">any</option>
                      <option value="true">has a trained model</option>
                      <option value="false">no model yet</option>
                    </select>
                  </div>
                  <div className="field-row">
                    <label htmlFor="sort">Order</label>
                    <select
                      id="sort"
                      value={filters.sort ?? "recent"}
                      onChange={(event) =>
                        setFilters((current) => ({
                          ...current,
                          sort: event.target.value as "recent" | "rows",
                        }))
                      }
                    >
                      <option value="recent">newest first</option>
                      <option value="rows">most data first</option>
                    </select>
                  </div>
                </div>
              </fieldset>

              {activeFilters > 0 && (
                <button
                  type="button"
                  className="ghost"
                  onClick={() => setFilters({ sort: filters.sort, q: filters.q })}
                >
                  Clear {activeFilters} filter{activeFilters === 1 ? "" : "s"}
                </button>
              )}
            </div>
          )}

          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {loading && <p className="muted">Loading…</p>}
          {!loading && rows.length === 0 && (
            <p className="muted">
              Nothing matches those filters. The counts on each chip are of all
              public projects, so a combination can still come back empty.
            </p>
          )}

          <ul className="project-list">
            {rows.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
