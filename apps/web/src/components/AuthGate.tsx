import { useEffect, useState } from "react";
import type { ReactNode } from "react";

type User = { id: string; email: string };
export default function AuthGate({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const expired = () => { setUser(null); setError("Your session expired. Please sign in again."); };
    window.addEventListener("tickaw:session-expired", expired);
    return () => window.removeEventListener("tickaw:session-expired", expired);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/v1/auth/me", { signal: controller.signal })
      .then(async response => {
        if (response.status === 401) return;
        if (!response.ok) throw new Error("Could not check your session. Please reload.");
        setUser(await response.json());
      }).catch(reason => { if (reason.name !== "AbortError") setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, []);
  async function logout() {
    setError("");
    try {
      const response = await fetch("/api/v1/auth/logout", { method: "POST" });
      if (!response.ok) throw new Error("Could not sign out. Please try again.");
      window.location.replace("/");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not sign out."); }
  }
  if (loading) return <main><p role="status">Checking your session…</p></main>;
  if (!user) return <main><p className="eyebrow">tickaw</p><h1>Sign in to tickaw</h1>
    <p>Ask questions about your spreadsheets. Your datasets and notebooks belong to your account.</p>
    {error && <p role="alert" className="error">{error}</p>}
    {new URLSearchParams(window.location.search).has("auth_error") && <p role="alert">Sign-in did not complete. You can try again.</p>}
    <a href="/api/v1/auth/login">Continue with Google</a></main>;
  return <><div className="account-bar"><span>{user.email}</span> <button onClick={logout}>Sign out</button>
    {error && <p role="alert">{error}</p>}</div>{children}</>;
}
