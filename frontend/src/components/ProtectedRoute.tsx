import { Navigate } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "../contexts/AuthContext";

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, isLoading, connectionError, retry } = useAuth();

  if (isLoading) {
    return <div role="status" className="p-8 text-center text-slate-600">Checking your session…</div>;
  }
  if (!user && connectionError) {
    return (
      <div role="alert" className="mx-auto mt-16 max-w-md rounded-lg border border-amber-300 bg-amber-50 p-6 text-sm text-amber-900">
        <div className="text-base font-semibold">Backend unavailable</div>
        <p className="mt-1">{connectionError}</p>
        <p className="mt-1 text-xs">Your sign-in has been kept. Start the backend (see the README) and try again.</p>
        <button type="button" onClick={retry} className="mt-3 rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700">
          Try again
        </button>
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}
