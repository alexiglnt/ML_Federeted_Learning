/* Who is signed in, for the whole app.
 *
 * The session itself is an HttpOnly cookie the browser holds and JavaScript
 * cannot read, so this context is only a cache of "who does the server say I
 * am". `/auth/me` returns null rather than 401 for a signed-out visitor,
 * because every page load asks and a signed-out visitor is a normal state, not
 * an error.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { auth as authApi, type User } from "./api";

interface AuthState {
  user: User | null;
  /** True until the first /auth/me settles. Guards against a flash of the
   *  signed-out header before we know the answer. */
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (payload: {
    email: string;
    password: string;
    full_name: string;
    institution?: string;
    country?: string;
  }) => Promise<void>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setUser(await authApi.me());
    } catch {
      // A failure here means the API is unreachable, not that the visitor is
      // signed out. Treating it as signed out is the honest fallback for
      // rendering, and the health check surfaces the real problem.
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      refresh,
      signIn: async (email, password) => setUser(await authApi.login(email, password)),
      signUp: async (payload) => setUser(await authApi.register(payload)),
      signOut: async () => {
        await authApi.logout();
        setUser(null);
      },
    }),
    [user, loading, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
