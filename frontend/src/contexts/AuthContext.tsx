import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import axios from "axios";
import * as authApi from "../api/auth";
import { getStoredToken, setStoredToken } from "../api/client";
import type { User } from "../types";
import { errorMessage } from "../utils/format";

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  /** Set when the session could not be checked because the backend is unreachable (the token is kept). */
  connectionError: string | null;
  retry: () => void;
  login: (email: string, password: string) => Promise<void>;
  register: (payload: authApi.RegisterPayload) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const token = getStoredToken();
    if (!token) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setConnectionError(null);
    authApi
      .fetchCurrentUser()
      .then(setUser)
      .catch((err: unknown) => {
        // A rejected token means "signed out"; an unreachable backend must NOT discard a valid session.
        if (axios.isAxiosError(err) && err.response?.status === 401) setStoredToken(null);
        else setConnectionError(errorMessage(err));
      })
      .finally(() => setIsLoading(false));
  }, [attempt]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await authApi.login({ email, password });
    setStoredToken(access_token);
    const currentUser = await authApi.fetchCurrentUser();
    setUser(currentUser);
  }, []);

  const register = useCallback(async (payload: authApi.RegisterPayload) => {
    await authApi.register(payload);
    await login(payload.email, payload.password);
  }, [login]);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } finally {
      setStoredToken(null);
      setUser(null);
    }
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, connectionError, retry, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
