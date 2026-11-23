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
    // ... (Keep your existing logic exactly as is)
    console.log("🔄 Processing SSE event:", data.type, data);
    
    if (data.type === "status") {
      const s = data.payload;
      setPhase(s.phase);
      setTasks(s.tasks || []);
      if (s.waiting_for) setWaitingFor(s.waiting_for);
      if (s.phase === "published") setSiteVersion(s.site_version || 1);
    } else if (data.type === "interrupt") {
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
    // ... (Keep your existing logic exactly as is)
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
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center p-6 relative overflow-hidden">
        {/* Decorative Background Elements */}
        <div className="absolute top-[-10%] left-[-10%] w-[40rem] h-[40rem] bg-indigo-500/20 dark:bg-indigo-500/10 rounded-full blur-[100px] pointer-events-none"></div>
        <div className="absolute bottom-[-10%] right-[-10%] w-[40rem] h-[40rem] bg-purple-500/20 dark:bg-purple-500/10 rounded-full blur-[100px] pointer-events-none"></div>

        <div className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl border border-white/40 dark:border-slate-800 p-8 sm:p-10 rounded-[2rem] shadow-2xl max-w-lg w-full relative z-10 transition-all duration-300">
          
          <div className="mb-8 text-center">
            <h1 className="text-3xl font-extrabold text-transparent bg-clip-text bg-gradient-to-r from-indigo-600 to-purple-600 dark:from-indigo-400 dark:to-purple-400 mb-2">
              SiteForge AI
            </h1>
            <p className="text-slate-500 dark:text-slate-400 text-sm">Instantly generate your dream website.</p>
          </div>

          <div className="space-y-5">
            <div>
              <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Brand / Website Name</label>
              <input 
                className="block w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-white/50 dark:bg-slate-950/50 px-4 py-3 text-slate-900 dark:text-white placeholder-slate-400 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 transition-all outline-none" 
                value={brandName} 
                onChange={(e) => setBrandName(e.target.value)} 
                placeholder="e.g., Acme Corp" 
              />
            </div>
            
            <div>
              <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">Business Niche</label>
              <input 
                className="block w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-white/50 dark:bg-slate-950/50 px-4 py-3 text-slate-900 dark:text-white placeholder-slate-400 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 transition-all outline-none" 
                value={niche} 
                onChange={(e) => setNiche(e.target.value)} 
                placeholder="e.g., Travelling, Hotel Booking, Hospitality" 
              />
            </div>
            
            <div>
              <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-1.5">What do you want to build?</label>
              <textarea 
                className="block w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-white/50 dark:bg-slate-950/50 px-4 py-3 text-slate-900 dark:text-white placeholder-slate-400 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/20 transition-all outline-none resize-none" 
                rows={4}
                value={prompt} 
                onChange={(e) => setPrompt(e.target.value)} 
                placeholder="Describe your vision, style, and key features..." 
              />
            </div>
            
            <button 
              onClick={handleStart} 
              disabled={!brandName || !niche || !prompt || streaming}
              className="w-full mt-2 flex items-center justify-center gap-2 bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 text-white font-semibold py-3.5 px-4 rounded-xl shadow-lg shadow-indigo-500/30 hover:shadow-indigo-500/50 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200"
            >
              {streaming ? (
                <>
                  <svg className="animate-spin -ml-1 mr-2 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                  Generating...
                </>
              ) : (
                <>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                  Generate Website
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // --- PHASE 2: Progress, Review, and Preview ---
  return (
    <div className="h-screen flex flex-col bg-slate-50 dark:bg-slate-950">
      {/* Header */}
      <header className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-md border-b border-slate-200 dark:border-slate-800 px-6 py-4 flex items-center justify-between sticky top-0 z-20">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white font-bold text-lg">
            S
          </div>
          <h1 className="font-bold text-lg text-slate-900 dark:text-white">SiteForge: {brandName}</h1>
        </div>
        <div className="flex items-center gap-3">
          {streaming && <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-indigo-600"></div>}
          <span className={`px-3 py-1 rounded-full text-xs font-bold tracking-wide uppercase ${
            phase === "published" ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" :
            phase === "waiting_for_approval" ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400" :
            "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400"
          }`}>
            {phase.replace(/_/g, " ")}
          </span>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar */}
        <div className="w-[400px] border-r border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50 p-6 overflow-y-auto flex flex-col gap-6">
          
          {/* Execution Plan Card */}
          <div className="bg-white dark:bg-slate-900 p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
            <h3 className="font-bold text-sm text-slate-800 dark:text-slate-200 mb-4 flex items-center gap-2">
              <svg className="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"></path></svg>
              Execution Plan
            </h3>
            <ul className="space-y-3">
              {tasks.map((t) => (
                <li key={t.key} className="flex items-center text-sm group">
                  {t.status === "completed" ? (
                    <svg className="w-5 h-5 text-green-500 mr-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                  ) : t.status === "failed" ? (
                    <svg className="w-5 h-5 text-red-500 mr-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                  ) : (
                    <svg className="animate-spin w-5 h-5 text-indigo-500 mr-3 flex-shrink-0" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                  )}
                  <span className="text-slate-700 dark:text-slate-300 font-medium capitalize">{t.agent.replace(/_/g, " ")}</span>
                  <span className={`ml-auto text-xs font-semibold px-2 py-0.5 rounded-md ${
                    t.status === "completed" ? "bg-green-50 text-green-600 dark:bg-green-900/20" : 
                    t.status === "failed" ? "bg-red-50 text-red-600 dark:bg-red-900/20" : 
                    "bg-indigo-50 text-indigo-600 dark:bg-indigo-900/20"
                  }`}>{t.status}</span>
                </li>
              ))}
              {tasks.length === 0 && <li className="text-slate-400 text-sm italic">Waiting for plan...</li>}
            </ul>
          </div>

          {/* Review Card */}
          {waitingFor?.type === "brand_review" && (
            <div className="bg-white dark:bg-slate-900 p-5 rounded-2xl border-l-4 border-indigo-500 shadow-lg shadow-indigo-500/10 relative overflow-hidden">
              <div className="absolute top-0 right-0 -mt-4 -mr-4 w-24 h-24 bg-indigo-500/10 rounded-full blur-2xl"></div>
              <h3 className="font-bold text-gray-900 dark:text-white mb-1 flex items-center gap-2">
                <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"></path></svg>
                Brand Review
              </h3>
              <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
                Revision {waitingFor.revision}. Review the generated brand guidelines.
              </p>
              <textarea 
                className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-950 px-3 py-2 text-sm text-slate-900 dark:text-white placeholder-slate-400 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 transition-all outline-none mb-3 resize-none" 
                placeholder="e.g., Make the primary color dark green..."
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                rows={2}
              />
              <div className="flex gap-2">
                <button onClick={() => handleResume("approve")} className="flex-1 bg-indigo-600 text-white py-2 rounded-lg text-sm font-semibold hover:bg-indigo-700 transition-colors">
                  Approve
                </button>
                <button onClick={() => handleResume("revise", feedback)} className="flex-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 py-2 rounded-lg text-sm font-semibold hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors">
                  Revise
                </button>
              </div>
            </div>
          )}

          {phase === "waiting_for_approval" && !waitingFor && (
            <div className="text-center text-slate-400 text-sm py-8 flex flex-col items-center gap-2">
              <div className="w-6 h-6 border-2 border-slate-300 border-t-indigo-500 rounded-full animate-spin"></div>
              Waiting for system input...
            </div>
          )}
        </div>

        {/* Right Preview Area */}
        <div className="flex-1 bg-slate-100 dark:bg-slate-950 flex flex-col relative">
          <div className="bg-white/50 dark:bg-slate-900/50 backdrop-blur-sm border-b border-slate-200 dark:border-slate-800 px-4 py-2 flex items-center justify-between z-10 absolute top-0 left-0 right-0">
            <div className="flex items-center gap-2">
              <div className="flex gap-1.5">
                <div className="w-3 h-3 rounded-full bg-red-400"></div>
                <div className="w-3 h-3 rounded-full bg-amber-400"></div>
                <div className="w-3 h-3 rounded-full bg-green-400"></div>
              </div>
              <span className="ml-2 text-xs font-semibold text-slate-500 uppercase tracking-wider">Live Preview (v{siteVersion})</span>
            </div>
          </div>
          
          <div className="flex-1 pt-10">
            {phase === "published" || phase === "wireframe_complete" ? (
              <iframe 
                src={`http://localhost:4000/preview/${projectId}/v${siteVersion}`} 
                className="w-full h-full border-none bg-white"
                title="Website Preview"
                sandbox="allow-same-origin allow-scripts"
              />
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-slate-400 p-8 text-center">
                <div className="relative mb-6">
                  <div className="absolute inset-0 bg-indigo-500 blur-xl opacity-20 rounded-full animate-pulse"></div>
                  <div className="w-16 h-16 rounded-2xl bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-xl flex items-center justify-center relative z-10">
                    <svg className="animate-spin w-8 h-8 text-indigo-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>
                  </div>
                </div>
                <h2 className="text-xl font-bold text-slate-700 dark:text-slate-300 mb-2">AI Agents at Work</h2>
                <p className="max-w-md mx-auto text-sm">We are currently assembling your components, styling the pages, and writing copy. Your preview will appear here automatically.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}