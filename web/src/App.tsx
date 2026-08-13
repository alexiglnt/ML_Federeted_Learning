import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import { useAuth } from "./lib/auth";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Me from "./pages/Me";
import NotFound from "./pages/NotFound";
import Notifications from "./pages/Notifications";
import ProjectDetail from "./pages/ProjectDetail";
import ProjectNew from "./pages/ProjectNew";
import ProjectPredict from "./pages/ProjectPredict";
import ProjectSettings from "./pages/ProjectSettings";
import ProjectUpload from "./pages/ProjectUpload";
import Projects from "./pages/Projects";
import Register from "./pages/Register";
import Variables from "./pages/Variables";

/** Gate for pages that need an account. Renders nothing while /auth/me is in
 *  flight, so a signed-in user reloading a private page is not bounced to the
 *  login form before the answer arrives. */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <p className="muted">Loading…</p>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="projects" element={<Projects />} />
        {/* Declared before ":slug" so "new" is not read as a project slug. */}
        <Route
          path="projects/new"
          element={
            <RequireAuth>
              <ProjectNew />
            </RequireAuth>
          }
        />
        <Route path="projects/:slug" element={<ProjectDetail />} />
        <Route
          path="projects/:slug/upload"
          element={
            <RequireAuth>
              <ProjectUpload />
            </RequireAuth>
          }
        />
        {/* Both need an account before they can say anything useful. The
            finer gates — model access, ownership — are the server's, and the
            pages render what it reports rather than deciding for themselves. */}
        <Route
          path="projects/:slug/predict"
          element={
            <RequireAuth>
              <ProjectPredict />
            </RequireAuth>
          }
        />
        <Route
          path="projects/:slug/settings"
          element={
            <RequireAuth>
              <ProjectSettings />
            </RequireAuth>
          }
        />
        <Route path="variables" element={<Variables />} />
        <Route
          path="notifications"
          element={
            <RequireAuth>
              <Notifications />
            </RequireAuth>
          }
        />
        <Route path="login" element={<Login />} />
        <Route path="register" element={<Register />} />
        <Route
          path="me"
          element={
            <RequireAuth>
              <Me />
            </RequireAuth>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
