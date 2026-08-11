import { Navigate, Route, Routes } from "react-router-dom";

import Layout from "./components/Layout";
import { useAuth } from "./lib/auth";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Me from "./pages/Me";
import NotFound from "./pages/NotFound";
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
        <Route path="variables" element={<Variables />} />
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
