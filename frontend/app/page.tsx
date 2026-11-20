"use client";

import { useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function Home() {
  const [projectId, setProjectId] = useState<string | null>(null);
  const [phase, setPhase] = useState<string>("idle");
  const [waitingFor, setWaitingFor] = useState<any>(null);
  const [tasks, setTasks] = useState<any[]>([]);
  const [siteVersion, setSiteVersion] = useState(1);
  const [streaming, setStreaming] = useState(false);
  
  const [brandName, setBrandName] = useState("");
  const [niche, setNiche] = useState("");
  const [prompt, setPrompt] = useState("");
  const [feedback, setFeedback] = useState("");

  const processSSEEvent = (data: any) => {
    console.log("🔄 Processing SSE event:", data.type, data);
    
    if (data.type === "status") {
      const s = data.payload;
      setPhase(s.phase);
      setTasks(s.tasks || []);
      if (s.waiting_for) setWaitingFor(s.waiting_for);
      if (s.phase === "published") setSiteVersion(s.site_version || 1);
    } else if (data.type === "interrupt") {
      console.log("🛑 Interrupt received:", data.payload);
      setWaitingFor(data.payload);
      setPhase("waiting_for_approval");
    } else if (data.type === "node") {
      if (data.update?.phase) setPhase(data.update.phase);
      if (data.update?.plan?.tasks) setTasks(data.update.plan.tasks);
    } else if (data.type === "error") {
      console.error("Stream error:", data.message);
    }
  };

  const handleStream = async (url: string, body?: any) => {
    setStreaming(true);
    setWaitingFor(null);
    
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    
    if (!res.ok) {
      console.error("Failed to start/resume project", await res.text());
      setStreaming(false);
      return;
    }
    
    const reader = res.body?.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    
    if (reader) {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";
        
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              console.log("📡 Raw SSE:", data);
              
              // The very first event contains the project ID
              if (data.type === "init" && data.project_id) {
                setProjectId(data.project_id);
              } else {
                processSSEEvent(data);
              }
            } catch (e) {
              console.error("Failed to parse SSE event:", e, line);
            }
          }
        }
      }
    }
    setStreaming(false);
  };

  const handleStart = () => {
    handleStream(`${API_URL}/v1/projects/`, { brand_name: brandName, niche, prompt });
  };

  const handleResume = (action: string, fb?: string) => {
    const payload = action === "approve" ? { action: "approve" } : { action: "revise", feedback: fb };
    handleStream(`${API_URL}/v1/projects/${projectId}/resume`, payload);
  };

  // --- PHASE 1: Onboarding ---
  if (!projectId) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-6">
        <div className="bg-white p-8 rounded-xl shadow-lg max-w-lg w-full">
          <h1 className="text-2xl font-bold text-gray-900 mb-6">SiteForge AI</h1>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">Brand / Website Name</label>
              <input className="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border" 
                value={brandName} onChange={(e) => setBrandName(e.target.value)} placeholder="e.g., Acme Corp" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Business Niche</label>
              <input className="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border" 
                value={niche} onChange={(e) => setNiche(e.target.value)} placeholder="e.g., SaaS, Hospitality" />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">What do you want to build?</label>
              <textarea className="mt-1 block w-full rounded-md border-gray-300 shadow-sm p-2 border" rows={4}
                value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Describe your vision..." />
            </div>
            <button onClick={handleStart} disabled={!brandName || !niche || !prompt || streaming}
              className="w-full bg-blue-600 text-white py-2 px-4 rounded-md hover:bg-blue-700 disabled:opacity-50">
              {streaming ? "Generating..." : "Generate Website"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // --- PHASE 2: Progress, Review, and Preview ---
  return (
    <div className="h-screen flex flex-col">
      <header className="bg-white border-b px-6 py-3 flex items-center justify-between">
        <h1 className="font-bold text-lg">SiteForge: {brandName}</h1>
        <div className="flex items-center gap-3">
          {streaming && <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>}
          <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium capitalize">
            {phase.replace(/_/g, " ")}
          </span>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        <div className="w-1/3 border-r bg-gray-50 p-4 overflow-y-auto flex flex-col gap-4">
          <div className="bg-white p-4 rounded-lg shadow-sm">
            <h3 className="font-semibold text-sm text-gray-500 mb-2 uppercase tracking-wide">Execution Plan</h3>
            <ul className="space-y-2">
              {tasks.map((t) => (
                <li key={t.key} className="flex items-center text-sm">
                  <span className={`w-2 h-2 rounded-full mr-2 ${
                    t.status === "completed" ? "bg-green-500" : 
                    t.status === "failed" ? "bg-red-500" : "bg-yellow-400 animate-pulse"
                  }`} />
                  <span className="text-gray-700">{t.agent.replace(/_/g, " ")}</span>
                  <span className="ml-auto text-xs text-gray-400">{t.status}</span>
                </li>
              ))}
            </ul>
          </div>

          {waitingFor?.type === "brand_review" && (
            <div className="bg-white p-4 rounded-lg shadow-md border-l-4 border-blue-500">
              <h3 className="font-bold text-gray-900 mb-2">Brand Guideline Ready for Review</h3>
              <p className="text-sm text-gray-600 mb-4">
                Revision {waitingFor.revision}. Review the colors, typography, and tone, or request changes.
              </p>
              <textarea 
                className="w-full border rounded p-2 text-sm mb-3" 
                placeholder="e.g., Make the primary color more premium, like dark green..."
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
              />
              <div className="flex gap-2">
                <button onClick={() => handleResume("approve")} className="flex-1 bg-green-600 text-white py-2 rounded text-sm hover:bg-green-700">
                  Approve & Continue
                </button>
                <button onClick={() => handleResume("revise", feedback)} className="flex-1 bg-gray-200 text-gray-800 py-2 rounded text-sm hover:bg-gray-300">
                  Request Changes
                </button>
              </div>
            </div>
          )}

          {phase === "waiting_for_approval" && !waitingFor && (
            <div className="text-center text-gray-500 text-sm py-8">Waiting for your input...</div>
          )}
        </div>

        <div className="w-2/3 bg-gray-100 flex flex-col">
          <div className="bg-white border-b px-4 py-2 flex items-center justify-between">
            <span className="text-sm font-semibold text-gray-600">Live Preview (v{siteVersion})</span>
          </div>
          {phase === "published" || phase === "wireframe_complete" ? (
            <iframe 
              src={`http://localhost:4000/preview/${projectId}/v${siteVersion}`} 
              className="flex-1 w-full h-full border-none bg-white"
              title="Website Preview"
              sandbox="allow-same-origin allow-scripts"
            />
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-400">
              <div className="text-center">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
                <p>AI Agents are building your website...</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}