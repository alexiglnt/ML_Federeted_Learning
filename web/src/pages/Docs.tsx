/* The guide. Read this if something on the site doesn't make sense or you
 * can't find it — that's the whole purpose of this page, and it's linked from
 * the header on every page so it's never more than one click away.
 *
 * Organised the way a confused user actually arrives here: not "what is this
 * platform" first, but "what does this badge mean" reachable in one jump from
 * the table of contents, because that's the question that sends most people
 * here. Deliberately exhaustive — the alternative is a user who can't find an
 * answer here either, which defeats the point.
 */

import { Link } from "react-router-dom";

const TOC: { id: string; label: string }[] = [
  { id: "overview", label: "What this platform is" },
  { id: "contributing", label: "Contributing: shared vs. summary-only" },
  { id: "review", label: "What happens after you submit" },
  { id: "access", label: "Who can see what" },
  { id: "indicators", label: "Reading the indicators — full glossary" },
  { id: "upload-steps", label: "Step by step: contributing a file" },
  { id: "creating", label: "Creating a project" },
  { id: "finding", label: "Finding a project to contribute to" },
  { id: "registry", label: "The variable registry" },
  { id: "notifications", label: "Notifications" },
  { id: "dashboard", label: "Your dashboard — “My work”" },
  { id: "privacy", label: "Privacy — what stays private" },
  { id: "faq", label: "Quick answers" },
];

export default function Docs() {
  return (
    <section className="docs">
      <p className="eyebrow">Guide</p>
      <h1>How this site works</h1>
      <p className="lead">
        Everything below is here because something on the site needed explaining
        somewhere. If you don't understand an indicator, don't know how to do
        something, or can't find a page you expect to exist, this is meant to be
        the first place you look.
      </p>

      <nav className="docs-toc" aria-label="Sections">
        <ul>
          {TOC.map((item) => (
            <li key={item.id}>
              <a href={`#${item.id}`}>{item.label}</a>
            </li>
          ))}
        </ul>
      </nav>

      {/* ------------------------------------------------------------------ */}
      <h2 id="overview">What this platform is</h2>
      <p>
        No single lab has enough machining measurements to fit a trustworthy
        model on its own — each condition costs machine time, so most labs have
        a handful of points. This site lets researchers who measure the same
        physical quantities pool their data and share the model that results,
        without necessarily handing their raw numbers to anyone but the project
        owner.
      </p>
      <p>
        The loop the whole platform runs on: someone declares a <strong>project</strong> —
        which quantities they measure as inputs, which one they predict as a
        target. Other researchers with the same measurements find that project
        (by browsing or by dropping a file) and <strong>contribute</strong> their
        data to it. Once the project owner accepts a contribution, the
        contributor gets <strong>access to the model</strong> it helped build.
        Reviewing exists because "share data, get the model" would otherwise be
        an open invitation to upload noise just to unlock something — see{" "}
        <a href="#review">What happens after you submit</a>.
      </p>
      <p className="muted small">
        A research tool. Models published here carry no warranty and are not
        intended for production machining decisions — see the note in the
        footer of every page.
      </p>

      {/* ------------------------------------------------------------------ */}
      <h2 id="contributing">Contributing: shared vs. summary-only</h2>
      <p>
        There are two ways to contribute, and they differ in exactly one thing:{" "}
        <strong>where your file is read.</strong> That's the whole privacy
        guarantee, and it's worth understanding precisely because it decides
        what you get back.
      </p>
      <div className="mode-grid">
        <article className="mode-card">
          <strong>Share your file</strong>
          <ul>
            <li>Your file is uploaded. The project owner can read it.</li>
            <li>Feeds both models the project trains (see "Model tracks" below).</li>
            <li>
              <strong>Unlocks the model</strong> once the owner accepts your
              contribution — you can then predict with it and export it.
            </li>
            <li>Every time anyone opens your file, it's logged and shown to you.</li>
          </ul>
        </article>
        <article className="mode-card">
          <strong>Keep your data, send only summaries</strong>
          <ul>
            <li>
              Your file is read <em>in your browser</em> and never leaves it.
              Only four numbers per quantity you predict are sent: the row
              count and three sums built from your inputs and target.
            </li>
            <li>
              Feeds the project's reference model <em>exactly</em> — this is not
              an approximation. A least-squares fit depends on the data only
              through those sums, and sums add up across labs the same way the
              rows would.
            </li>
            <li>You're credited as a contributor, and your data widens the published range.</li>
            <li>
              <strong>Does not unlock the model.</strong> You can share your
              file later to change that — see below.
            </li>
          </ul>
        </article>
      </div>
      <p className="muted small">
        Being honest about the limit of the summary-only mode: those four sums
        are not anonymous. On very few rows they can disclose a lot about the
        data behind them, which is why every project enforces a minimum row
        count before it will accept a contribution at all.
      </p>
      <p>
        Changed your mind after sending summaries? Open the project page, find
        your contribution under "My contributions", and use{" "}
        <strong>Share the file</strong>. That doesn't create a second
        contribution — it turns the same one from summary-only into shared, so
        your data is never counted twice. It unlocks the model immediately if
        the contribution was already accepted.
      </p>
      <p className="muted small">
        A project can also turn summary-only contributions off entirely (its
        owner's choice) — if you don't see that option when contributing, that's
        why.
      </p>

      {/* ------------------------------------------------------------------ */}
      <h2 id="review">What happens after you submit</h2>
      <p>
        If you're the project owner, your own upload is accepted immediately —
        reviewing your own data would be theatre. Anyone else's contribution
        lands <span className="badge warn">pending</span> and waits for the
        owner's decision. Until then it counts nowhere: not in the row total,
        not in the model, not in the published range.
      </p>
      <p>Four things can happen to a contribution, and only two people can move it:</p>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Status</th>
              <th scope="col">Meaning</th>
              <th scope="col">Who decides</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><span className="badge warn">pending</span></td>
              <td>Submitted, awaiting the owner's decision. Not yet in the model.</td>
              <td>—</td>
            </tr>
            <tr>
              <td><span className="badge">accepted</span></td>
              <td>In the model. If it was a shared file, you now have model access.</td>
              <td>The project owner</td>
            </tr>
            <tr>
              <td><span className="badge danger">rejected</span></td>
              <td>
                Left out of the model. Not final — the owner can accept it later
                if they reconsider.
              </td>
              <td>The project owner</td>
            </tr>
            <tr>
              <td><span className="badge muted-badge">withdrawn</span></td>
              <td>
                Pulled back by you. Final — once withdrawn, the owner cannot
                reinstate it; that decision isn't theirs to make.
              </td>
              <td>You, the contributor</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        Accepting or rejecting a <em>shared</em> contribution also grants or
        removes your model access, and queues a retrain — every published model
        is a full refit of the currently accepted data, never a patch, so
        dropping a contribution is "retrain without it," not an attempt to
        surgically undo its effect. A <em>summary-only</em> contribution never
        grants access either way, whatever the decision.
      </p>
      <p>
        You'll be told about it: submitting notifies the project owner, and
        their decision notifies you back, review note included — see{" "}
        <a href="#notifications">Notifications</a>.
      </p>

      <h3>The two scores the owner reviews on</h3>
      <p>
        When a contribution arrives, the site immediately computes two numbers
        for it, and they answer two different questions:
      </p>
      <ul>
        <li>
          <strong>Transfer score</strong> — does the model as it stood before
          your contribution already predict your measurements, unchanged? Low
          means your data comes from a regime the current model doesn't reach.
        </li>
        <li>
          <strong>Refit score</strong> — fitted on your rows alone and
          cross-validated, is your data internally consistent and predictable
          at all? Low means it looks like noise, or a different measurement
          convention than everyone else's.
        </li>
      </ul>
      <p>
        The trap worth knowing about: <strong>poor transfer with a good refit
        is not a bad contribution</strong> — it's clean data from a regime the
        model has never seen, which is the single most valuable kind of
        contribution there is, because it's what extends the model's validity
        domain. The review card states this reading in words next to the
        numbers, exactly because it's the case people misread:
      </p>
      <p className="reading valuable">
        <strong>Clean data from a regime the model does not cover.</strong> The
        measurements are highly predictable on their own, but the published
        model does not reach them. This is the most valuable kind of
        contribution there is — it extends the validity domain. Do not reject
        it for the poor transfer score.
      </p>
      <p className="reading poor">
        <strong>Worth a hard look.</strong> The model does not predict this
        data, and neither does a model fitted on the data itself. That pattern
        is what noise looks like.
      </p>
      <p className="muted small">
        A third check, <strong>poolability</strong>, is available to the owner
        for shared contributions on demand: it fits the model on every other
        accepted contributor and asks whether it predicts this one (a
        held-out fit), and whether accepting this contribution would help or
        hurt the model's honest, cross-lab score for everyone else. It is
        checked live against the current accepted pool rather than stored,
        because the answer changes as soon as another pending contribution is
        decided.
      </p>

      {/* ------------------------------------------------------------------ */}
      <h2 id="access">Who can see what</h2>
      <p>
        Three roles, and the site always tells you which one you have on a
        project via a badge in its header, <span className="badge">you: owner</span>{" "}
        for example:
      </p>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Role</th>
              <th scope="col">How you get it</th>
              <th scope="col">Can use the model</th>
              <th scope="col">Can read raw files</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Owner</strong></td>
              <td>Created the project</td>
              <td>Yes</td>
              <td>Every contributor's file</td>
            </tr>
            <tr>
              <td><strong>Contributor</strong></td>
              <td>An accepted shared contribution</td>
              <td>Yes</td>
              <td>Only their own file</td>
            </tr>
            <tr>
              <td><strong>Viewer</strong></td>
              <td>Explicitly invited by the owner</td>
              <td>Yes</td>
              <td>No</td>
            </tr>
            <tr>
              <td>Everyone else, signed in or not</td>
              <td>—</td>
              <td>No — scores are public, the model is not</td>
              <td>No</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p>
        That split — <strong>metrics are public, the model itself is not</strong> —
        is the incentive the whole site runs on: it's how you can judge whether
        a project's model is worth having before deciding to hand over your
        data. What "using the model" unlocks is the coefficients/equation, the
        prediction page, and the JSON export. What stays gated behind{" "}
        <strong>owner</strong> specifically is other contributors' raw files —
        a contributor never sees another contributor's file, however much they
        themselves have contributed.
      </p>
      <p className="muted small">
        A summary-only contribution earns none of this — see{" "}
        <a href="#contributing">Contributing</a>.
      </p>

      {/* ------------------------------------------------------------------ */}
      <h2 id="indicators">Reading the indicators — full glossary</h2>
      <p>
        Every badge, score and coloured bar on the site, in one place. If you
        landed here from elsewhere wondering what something meant, this is
        probably the section you want.
      </p>

      <h3>Badges</h3>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">What you see</th>
              <th scope="col">Meaning</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><span className="badge">draft</span></td>
              <td>A project with no accepted data yet — no model has been trained, but it can still take contributions.</td>
            </tr>
            <tr>
              <td><span className="badge warn">archived</span></td>
              <td>The owner has closed the project to new contributions.</td>
            </tr>
            <tr>
              <td><span className="badge">you: owner</span> / <span className="badge">you: contributor</span></td>
              <td>Your role on this specific project — see <a href="#access">Who can see what</a>.</td>
            </tr>
            <tr>
              <td><span className="badge warn">pending</span> / <span className="badge">accepted</span> / <span className="badge danger">rejected</span> / <span className="badge muted-badge">withdrawn</span></td>
              <td>A contribution's status — see <a href="#review">What happens after you submit</a>.</td>
            </tr>
            <tr>
              <td><span className="badge">exact</span></td>
              <td>A column heading in your file matched a registry quantity exactly.</td>
            </tr>
            <tr>
              <td><span className="badge warn">approximate · 82%</span></td>
              <td>
                A fuzzy name match, with a confidence — a suggestion, not a
                verdict. Always worth checking: a column matched to the wrong
                quantity fits the model to the wrong thing, and nothing looks
                broken afterwards.
              </td>
            </tr>
            <tr>
              <td><span className="badge">chosen by you</span></td>
              <td>You picked this column yourself, overriding (or where there was no) suggestion.</td>
            </tr>
            <tr>
              <td><span className="badge">summary statistics only</span></td>
              <td>This contribution arrived without a file — see the summary-only mode above.</td>
            </tr>
            <tr>
              <td><span className="badge">read in your browser</span></td>
              <td>Shown while contributing in summary-only mode, confirming the file never left your machine.</td>
            </tr>
            <tr>
              <td><span className="badge">reference</span></td>
              <td>Marks a reference-track model card among the main-track ones — see "Model tracks" below.</td>
            </tr>
            <tr>
              <td><span className="badge"> project owner</span></td>
              <td>In the access log, marks a file download made by the project owner rather than a peer.</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h3>The model's scores</h3>
      <p>
        Shown in a deliberate order, worst-to-best-trusted read bottom to top —
        the site always leads with the harshest, most honest number rather than
        the flattering one:
      </p>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Score</th>
              <th scope="col">What it actually measures</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>R² across labs</strong> (leave-one-lab-out)</td>
              <td>
                The headline number. Trained on every contributor but one,
                tested on the one left out — repeated for each. It's the only
                score that answers "does this model work anywhere other than
                where it was built", and it needs at least two contributors to
                exist at all.
              </td>
            </tr>
            <tr>
              <td><strong>R² out of sample</strong> (cross-validated)</td>
              <td>Ordinary cross-validation within the pooled data. Shown alongside RMSE in the same units as the target.</td>
            </tr>
            <tr>
              <td><strong>Training R²</strong></td>
              <td>
                Shown last, quietly, and explicitly labelled "not a measure of
                performance" — five parameters fitted on seven points look
                excellent whatever the data says. Kept only for completeness.
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <h3>A contribution's scores, at review time</h3>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">Score</th>
              <th scope="col">Question it answers</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Transfer R²</strong></td>
              <td>Does the model as published (before this contribution) already predict these rows, unchanged?</td>
            </tr>
            <tr>
              <td><strong>Refit R²</strong></td>
              <td>Fitted on these rows alone and cross-validated: are they internally consistent?</td>
            </tr>
            <tr>
              <td><strong>Poolability — held-out fit / pool effect</strong></td>
              <td>
                Owner-only, on demand: does everyone else's accepted data
                predict this contributor, and would accepting them help or hurt
                the model's honest cross-lab score for everyone? Shared
                contributions only — there are no raw rows to hold out for a
                summary-only one.
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="muted small">
        A colour code runs through all of these: green/accent for good, amber
        for weak, red for poor — deliberately coarse, because these numbers are
        read as "good, bad, or worth a look," not to three decimal places.
      </p>

      <h3>The validity-domain bar</h3>
      <p>
        Under each input on a project page, one bar draws three different
        things that are routinely confused with each other:
      </p>
      <ul>
        <li><strong>declared</strong> — the range the owner said the project is about. A claim, nothing more.</li>
        <li><strong>owner's data</strong> — where the owner's own measurements actually sit.</li>
        <li><strong>with contributions</strong> — how far other labs' accepted data pushed that.</li>
      </ul>
      <p>
        Only the last two license belief in a prediction — never the declared
        range. That's why the prediction page warns you when a value falls
        outside the range there's <em>data</em> for, and never merely outside
        what was declared: a model trusted over a range nobody actually
        measured is exactly the failure this whole feature exists to prevent.
        The gap between the owner's own band and the full covered band, made
        visible, is this platform's reason to exist: it's the part of the
        domain that pooling bought.
      </p>

      <h3>Model tracks and engines</h3>
      <p>
        Every trained project publishes <strong>two</strong> models per
        quantity it predicts, not one:
      </p>
      <ul>
        <li>
          <strong>Main track</strong> — the owner's chosen engine, fitted on{" "}
          <em>shared</em> data only. This is "the model" in the everyday sense —
          what you predict with and export.
        </li>
        <li>
          <strong>Reference track</strong> — always a linear-family engine, fed
          by <em>every</em> accepted contribution, summary-only ones included.
          It exists so that a contributor who never uploaded a file still
          counts toward something, and it's a useful baseline: if the owner's
          chosen engine doesn't beat it, that itself is a finding.
        </li>
      </ul>
      <p>Six engines exist for the main track; only three can also absorb summary-only contributions into the reference track, because they're the ones whose fit is exact from summed statistics alone:</p>
      <ul>
        <li>Linear regression, Ridge regression, PIML (linear with physical priors) — <em>can</em> be fed by summary-only contributions.</li>
        <li>Gaussian process regression, Gradient boosting, Random forest — main track only; these need the individual rows and no summary replaces them.</li>
      </ul>
      <p>
        <strong>Engine comparison.</strong> Each version also scores all six
        engines on the same shared rows, out of sample — R² across labs when
        there are at least two contributors, cross-validated R² otherwise — and
        shows the ranking on the project page. PIML's and ridge's
        hyperparameters are chosen inside each fold, so no engine is flattered
        by having been tuned on the rows it is scored on. The site then{" "}
        <em>suggests</em> a main engine: the best average score, except that
        engines within 0.02 of the best count as tied and the simplest of them
        wins (linear family first — PIML ahead when the project declares
        physical priors — then boosting, forest, Gaussian process). It never
        switches on its own: the owner decides, in one click. On a first file
        from a single lab the suggestion is provisional, and the comparison is
        re-run at every version so it can change as other labs contribute.
      </p>

      {/* ------------------------------------------------------------------ */}
      <h2 id="upload-steps">Step by step: contributing a file</h2>
      <p>From a project page, "Contribute my measurements" walks through five steps:</p>
      <ol className="steps">
        <li>
          <h3>Choose how</h3>
          <p>Share your file, or keep it and send only summaries. See the comparison above — pick based on whether you want model access now.</p>
        </li>
        <li>
          <h3>Pick your file</h3>
          <p>
            CSV, tab-separated text, or .xlsx for a shared contribution;
            CSV/TSV only for summary-only, since reading a spreadsheet needs a
            library and that page deliberately loads no third-party code — it's
            what lets you check nothing leaves your browser.
          </p>
        </li>
        <li>
          <h3>Check how it was read</h3>
          <p>
            A preview table of your actual rows. This step exists because a
            file read with the wrong decimal mark or the wrong header row
            parses without complaint — the mistake is obvious in a preview and
            invisible in a summary. If a column of numbers reads as text, the
            decimal mark was misread.
          </p>
        </li>
        <li>
          <h3>Match your columns</h3>
          <p>
            Confirm which of your columns is which registry quantity. Every
            match — even an exact one — stays something you confirm, not
            something assumed silently.
          </p>
        </li>
        <li>
          <h3>Describe the measurement, and submit</h3>
          <p>
            Measurement method matters: XRD and hole-drilling residual stress
            readings can differ by tens of MPa on the same part, and recording
            the method is what lets that be accounted for rather than silently
            pooled as if it were the same thing.
          </p>
        </li>
      </ol>
      <p>
        After submitting, a shared file that isn't your own project lands{" "}
        <span className="badge warn">pending</span> and you're told what
        happens next; you'll be notified the moment the owner decides.
      </p>

      {/* ------------------------------------------------------------------ */}
      <h2 id="creating">Creating a project</h2>
      <p>From "Create a project," in short:</p>
      <ul>
        <li>
          Pick your <strong>inputs</strong> and the <strong>target</strong> you
          predict from the <a href="#registry">variable registry</a> — a
          quantity can't be both. Input order is part of the contract: it's
          recorded and later contributions must match it.
        </li>
        <li>
          Missing a quantity? Propose it inline — it becomes usable in your own
          project immediately and is reviewed for the shared registry in
          parallel, so you're never blocked waiting on moderation.
        </li>
        <li>
          Optionally set a <strong>physical prior</strong> per input for the
          PIML engine — the sign a coefficient is not supposed to take (e.g.
          "raising cutting speed should not decrease residual stress").
          It's a soft push, not a hard rule: a fit that strongly contradicts it
          still gets the "forbidden" sign if the data really says so.
        </li>
        <li>
          Choose the <strong>main engine</strong> (provisionally — once the
          first file is in, the project page compares every engine on it and
          suggests one), <strong>visibility</strong>{" "}
          (public, or unlisted — reachable by link but absent from search), and
          a <strong>licence</strong>.
        </li>
        <li>
          The project starts as <span className="badge">draft</span> — there's
          no model to publish until it holds accepted data. Uploading your own
          first dataset moves it to <strong>active</strong>.
        </li>
      </ul>

      {/* ------------------------------------------------------------------ */}
      <h2 id="finding">Finding a project to contribute to</h2>
      <p>Two ways in, on the Projects page:</p>
      <h3>Match my file</h3>
      <p>
        Drop the file you already have and every public project is ranked by
        how well it fits — deliberately never reduced to a pass/fail. Each
        result shows inputs matched out of total (with approximate matches
        flagged for a check), which targets are present, and what fraction of{" "}
        <em>your rows</em> fall inside the range the project has data for.
      </p>
      <p className="reading valuable small">
        A low domain fraction is not a warning — it's the mark of a
        contribution that would extend the project's validity domain, which is
        the most valuable kind there is. The card says so rather than flagging
        it red, on purpose: presented as a failure it would drive away exactly
        the data the platform most needs.
      </p>
      <p className="muted small">
        Nothing is stored by this. Your file is parsed in memory and discarded
        with the response — no upload, no record. Checking whether contributing
        is worth your time shouldn't require handing your data over first.
      </p>
      <h3>Browse and filter</h3>
      <p>
        Filter by material, process, what a project predicts, and which inputs
        it uses — the last one accumulates (a project must declare every input
        you pick, since the question is "which projects can use the columns I
        have"), while the others are alternatives within their own group. Also
        filterable by minimum row count and whether a model has been trained
        yet.
      </p>

      {/* ------------------------------------------------------------------ */}
      <h2 id="registry">The variable registry</h2>
      <p>
        Every input and target is picked from a shared list of physical
        quantities rather than named freely — that's what makes searching by
        variable reliable, lets units convert automatically, and lets an
        uploaded column be matched with confidence. It's public and browsable
        on the <Link to="/variables">Variables</Link> page without an account.
      </p>
      <p>
        Missing something you measure? Propose it while creating a project or
        contributing — it's usable by you immediately and reviewed for
        inclusion in the shared registry in parallel, so the registry's
        completeness is never the reason you give up.
      </p>

      {/* ------------------------------------------------------------------ */}
      <h2 id="notifications">Notifications</h2>
      <p>
        The bell icon in the header. It fires on exactly two things:
      </p>
      <ul>
        <li>A contribution lands on one of your projects → you, the owner, are notified.</li>
        <li>You get a decision (accepted or rejected) on your own contribution → you're notified, review note included.</li>
      </ul>
      <p>
        Nothing else raises a notification today — withdrawing your own
        contribution or sharing a file you already summarised doesn't, since
        those are your own actions and there's nothing to tell you that you
        don't already know. Click the bell for the last few, or open{" "}
        <Link to="/notifications">the full notifications page</Link> for
        everything. Unread ones are highlighted; opening one marks it read and
        takes you to the project it's about.
      </p>

      {/* ------------------------------------------------------------------ */}
      <h2 id="dashboard">Your dashboard — "My work"</h2>
      <p>
        Signed in, click your name to reach it. Four sections, each independent
        so one loading slowly never blanks the rest:
      </p>
      <ul>
        <li><strong>Projects I own</strong> — everything you created.</li>
        <li>
          <strong>Awaiting my review</strong> — every pending contribution
          across every project you own, gathered in one place instead of
          having to open each project to check.
        </li>
        <li>
          <strong>Contributions I've made</strong> — everything you've
          submitted anywhere, with its current status and any review note.
        </li>
        <li>
          <strong>Projects I can access</strong> — everywhere your accepted,
          shared contributions have unlocked the model.
        </li>
      </ul>

      {/* ------------------------------------------------------------------ */}
      <h2 id="privacy">Privacy — what stays private</h2>
      <ul>
        <li>A shared file is readable only by the project owner and by you, its contributor — never by another contributor, however much they've themselves contributed.</li>
        <li>Every time your file is opened, it's logged, and that log is shown to you — not just kept internally for the owner.</li>
        <li>A summary-only contribution never uploads a measurement — only four sums per target quantity, computed in your browser and never leaving it except as those four numbers.</li>
        <li>"Match my file," used to find a project, stores nothing at all — the file is read in memory and discarded with the response.</li>
        <li>Metrics (the model's scores) are public to anyone; the model itself — coefficients, prediction, export — is not, until you've contributed and been accepted.</li>
      </ul>

      {/* ------------------------------------------------------------------ */}
      <h2 id="faq">Quick answers</h2>
      <dl className="faq">
        <dt>Why can't I see the model / use "Predict"?</dt>
        <dd>
          You need model access on that project — an accepted <em>shared</em>{" "}
          contribution, or an owner/viewer role. See{" "}
          <a href="#access">Who can see what</a>.
        </dd>

        <dt>My contribution has said "pending" for a while — what do I do?</dt>
        <dd>
          Nothing to do on your end; it's the project owner's decision. You'll
          be notified the moment they act on it — see{" "}
          <a href="#notifications">Notifications</a>.
        </dd>

        <dt>I contributed summary statistics — can I still get model access?</dt>
        <dd>
          Yes: open the project, find your contribution, and use "Share the
          file." It converts the same contribution rather than creating a new
          one, and unlocks access immediately if it's already accepted.
        </dd>

        <dt>Why does my prediction say "extrapolation"?</dt>
        <dd>
          One of your inputs sits outside the range the model actually has{" "}
          <em>data</em> for — not outside the range the project merely
          declared. The prediction is still given; it's just a different kind
          of claim than one inside the covered range.
        </dd>

        <dt>Why are there two models on a project page (main and reference)?</dt>
        <dd>
          See "Model tracks and engines" above — the reference model exists so
          summary-only contributors count toward something even when the main
          engine can't use their data directly.
        </dd>

        <dt>Is my raw data ever shown publicly?</dt>
        <dd>
          No. The fact that you contributed, and how many rows, is public
          credit. The file itself is never shown to anyone but the project
          owner and you.
        </dd>

        <dt>What's the difference between "draft," "active," and "archived"?</dt>
        <dd>
          Draft: no accepted data yet. Active: holds accepted data and trains a
          model. Archived: the owner has closed it to new contributions —
          existing data and the model stay visible.
        </dd>

        <dt>Still stuck?</dt>
        <dd>
          This site is under active development — see <code>ROADMAP.md</code>{" "}
          in the repository for what's built, what isn't yet, and known gaps.
        </dd>
      </dl>
    </section>
  );
}
