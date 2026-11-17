"use client";
import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  const [db, setDb] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/health/db`)
      .then(async (r) => {
        if (!r.ok) throw new Error(`API answered ${r.status}: ${await r.text()}`);
        return r.json();
      })
      .then(setDb)
      .catch((e) =>
        setErr(
          `${e}\n\nCould not reach ${API}/health/db.\n` +
            `- Is the backend running?  docker compose ps / docker compose logs backend\n` +
            `- Open ${API}/health in your browser: it should show {"status":"ok"}\n` +
            `- Browser calling from another origin? Add it to CORS_ORIGINS in .env`
        )
      );
  }, []);

  return (
    <main style={{ maxWidth: 640, margin: "4rem auto", padding: "0 1rem" }}>
      <h1>SiteForge</h1>
      <p>Step 1 scaffold: frontend is up. Backend/DB status:</p>
      <pre style={{ whiteSpace: "pre-wrap" }}>{err ?? (db ? JSON.stringify(db, null, 2) : "loading...")}</pre>
    </main>
  );
}
