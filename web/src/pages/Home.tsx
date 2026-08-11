import { Link } from "react-router-dom";

export default function Home() {
  return (
    <>
      <section className="hero">
        <p className="eyebrow">Machining measurements, pooled across labs</p>
        <h1>No single lab has enough data. Together, they might.</h1>
        <p className="lead">
          A researcher measuring residual stress on Ti-6Al-4V may have seven
          conditions. Each one costs machine time, money and effort — which is
          why models in this field are fitted on almost nothing. This platform
          lets researchers who measure the same quantities pool their data and
          share the resulting model.
        </p>
        <div className="cta-row">
          <Link to="/projects" className="primary button-like">
            Find a project matching your data
          </Link>
          <Link to="/register" className="ghost button-like">
            Create an account
          </Link>
        </div>
      </section>

      <section className="how">
        <h2>How it works</h2>
        <ol className="steps">
          <li>
            <h3>Declare what you measure</h3>
            <p>
              Create a project by picking your input variables from a shared
              registry of physical quantities, and say what you predict. Upload
              your own measurements, and a model is fitted on them.
            </p>
          </li>
          <li>
            <h3>Others find you</h3>
            <p>
              A researcher with the same inputs searches — by material, process,
              variables and range, or simply by dropping their own file and
              letting the site rank projects by how well they match.
            </p>
          </li>
          <li>
            <h3>Contribute, and get the model</h3>
            <p>
              Share your data and, once the project owner accepts it, you get
              access to the model it helped build. Only the owner ever sees the
              files themselves.
            </p>
          </li>
        </ol>
      </section>

      <section className="two-modes">
        <h2>Two ways to contribute</h2>
        <div className="mode-grid">
          <article className="mode-card">
            <h3>Share your data</h3>
            <p className="muted">Your file is uploaded and readable by the project owner.</p>
            <ul>
              <li>Feeds every model the project trains</li>
              <li>You are credited as a contributor</li>
              <li>
                <strong>You get access to the model</strong>
              </li>
            </ul>
          </article>
          <article className="mode-card">
            <h3>Contribute without sharing</h3>
            <p className="muted">
              Only summary sums leave your browser. No measurement is uploaded.
            </p>
            <ul>
              <li>Still improves the project's reference model, exactly</li>
              <li>You are credited as a contributor</li>
              <li>
                <strong>No access to the model</strong> — share your data to
                unlock it
              </li>
            </ul>
          </article>
        </div>
        <p className="muted small">
          The second mode is possible because a least-squares fit depends on the
          data only through a handful of sums, and those sums add up across labs.
          Pooling them refits the model exactly — nothing is averaged or
          approximated.
        </p>
      </section>
    </>
  );
}
