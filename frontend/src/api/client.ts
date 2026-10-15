import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 60_000,
});

const TOKEN_STORAGE_KEY = "ocean_platform_token";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredToken(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

apiClient.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// An expired/invalid token on a protected call: drop it and send the user to the login page once.
apiClient.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (axios.isAxiosError(error) && error.response?.status === 401 && getStoredToken()) {
      const url = error.config?.url ?? "";
      if (!url.includes("/auth/login") && !url.includes("/auth/register")) {
        setStoredToken(null);
        if (window.location.pathname !== "/login") window.location.assign("/login?expired=1");
      }
    }
    return Promise.reject(error);
  },
);
