"use client";

import { useEffect, useState, useCallback } from "react";
import {
  StreamVideo,
  StreamVideoClient,
  StreamCall,
  SpeakerLayout,
  CallControls,
  StreamTheme,
  Call
} from "@stream-io/video-react-sdk";
import "@stream-io/video-react-sdk/dist/css/styles.css";
import { v4 as uuidv4 } from "uuid";
import { Play, Square, Loader2, ShieldCheck, Activity } from "lucide-react";

const apiKey = process.env.NEXT_PUBLIC_STREAM_API_KEY!;
const backendUrl = "/api/backend";

export default function Home() {
  const [client, setClient] = useState<StreamVideoClient | null>(null);
  const [call, setCall] = useState<Call | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isConnected, setIsConnected] = useState(false);

  const [sessionId, setSessionId] = useState<string | null>(null);

  const startCall = useCallback(async () => {
    try {
      setIsConnecting(true);

      const userId = uuidv4();
      const callId = uuidv4();

      // Get short-lived token from Next.js API route
      const res = await fetch("/api/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId }),
      });
      const { token } = await res.json();

      if (!token) throw new Error("Could not fetch token");

      const _client = new StreamVideoClient({
        apiKey,
        user: { id: userId, name: "Clinician" },
        token,
      });

      const _call = _client.call("default", callId);
      await _call.join({ create: true });

      setClient(_client);
      setCall(_call);
      setIsConnected(true);

      // Now tell the python backend to join
      const backendRes = await fetch(backendUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ call_id: callId, call_type: "default" }),
      });
      if (backendRes.ok) {
        const backendData = await backendRes.json();
        setSessionId(backendData.session_id);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setIsConnecting(false);
    }
  }, []);

  const endCall = useCallback(async () => {
    try {
      if (sessionId) {
        // Terminate the backend agent
        await fetch(`${backendUrl}/${sessionId}`, {
          method: "DELETE",
        }).catch(err => console.warn("Agent termination failed:", err));
      }

      if (call) {
        await call.leave();
      }
      if (client) {
        await client.disconnectUser();
      }
    } catch (e) {
      console.warn("Could not cleanly exit call:", e);
    } finally {
      setClient(null);
      setCall(null);
      setSessionId(null);
      setIsConnected(false);
    }
  }, [call, client, sessionId]);

  // Removed aggressive useEffect cleanup that was causing React 18 Strict Mode to prematurely disconnect the call.

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white font-sans selection:bg-indigo-500/30">
      {/* Background gradients */}
      <div className="fixed inset-0 z-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] rounded-full bg-indigo-900/20 blur-[120px]" />
        <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] rounded-full bg-blue-900/20 blur-[120px]" />
      </div>

      <div className="relative z-10 flex flex-col min-h-screen max-w-7xl mx-auto px-6 py-8">
        <header className="flex items-center justify-between mb-8 pb-6 border-b border-white/10">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 flex items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-blue-600 shadow-lg shadow-indigo-500/20">
              <ShieldCheck className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-semibold tracking-tight">Medproctor AI</h1>
              <p className="text-sm text-zinc-400">Live AI Safety Monitor</p>
            </div>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/5 border border-white/10">
            <Activity className="h-4 w-4 text-emerald-400" />
            <span className="text-sm font-medium text-emerald-400">System Ready</span>
          </div>
        </header>

        <main className="flex-1 flex flex-col">
          {!isConnected ? (
            <div className="flex-1 flex flex-col items-center justify-center max-w-2xl mx-auto text-center">
              <div className="mb-8 p-6 rounded-2xl bg-white/5 border border-white/10 backdrop-blur-md">
                <ShieldCheck className="h-16 w-16 mx-auto mb-4 text-indigo-400" />
                <h2 className="text-2xl font-bold mb-2">Start Medication Administration</h2>
                <p className="text-zinc-400 mb-6">
                  Initialize the AI proctor to begin the session. Ensure your camera and microphone are
                  ready. The AI will monitor protocol compliance including PPE, hand hygiene, and
                  drug identification.
                </p>
                <button
                  onClick={startCall}
                  disabled={isConnecting}
                  className="group relative inline-flex items-center justify-center gap-2 px-8 py-4 font-semibold text-white transition-all duration-200 bg-indigo-600 border border-transparent rounded-full hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-600 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isConnecting ? (
                    <>
                      <Loader2 className="h-5 w-5 animate-spin" />
                      Connecting...
                    </>
                  ) : (
                    <>
                      <Play className="h-5 w-5 fill-current" />
                      Initialize Session
                    </>
                  )}
                  {/* Subtle glow effect */}
                  <div className="absolute inset-0 -z-10 rounded-full bg-indigo-600 opacity-20 blur-xl transition-opacity group-hover:opacity-40" />
                </button>
              </div>
            </div>
          ) : (
            <div className="flex-1 relative flex flex-col rounded-3xl overflow-hidden border border-white/10 bg-black/50 shadow-2xl backdrop-blur-sm">
              {client && call && (
                <StreamVideo client={client}>
                  <StreamCall call={call}>
                    <StreamTheme className="flex-1 w-full h-full flex flex-col">
                      <div className="flex-1 min-h-0 relative">
                        <SpeakerLayout participantsBarPosition="bottom" />
                      </div>
                      <div className="p-4 bg-black/80 border-t border-white/10 flex justify-center backdrop-blur-md">
                        <CallControls onLeave={endCall} />
                      </div>
                    </StreamTheme>
                  </StreamCall>
                </StreamVideo>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
