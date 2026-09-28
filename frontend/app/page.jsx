"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { IMessageFrame } from "./imessage";

const API = "/api";

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, { credentials: "include", cache: "no-store", ...options });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try { const body = await response.json(); detail = body.detail || detail; } catch {}
    throw new Error(detail);
  }
  return response.json();
}

function CompletionScreen({ conversation, onReset, onLogout, busy, error }) {
  const { profile, onboarding } = conversation;
  const transcript = (conversation.transcript || []).map(({ role, modality, content }) =>
    `${role === "assistant" ? "Assistant" : "User"} · ${modality}: ${content}`).join("\n\n");
  const gmail = onboarding.GoogleProducts?.Gmail;
  const google = onboarding.GoogleProducts?.Google;
  const hasGoogleAccount = gmail === true || google === true || Boolean(profile.Usergmail);
  const googleKnown = typeof gmail === "boolean" || typeof google === "boolean" || Boolean(profile.Usergmail);
  const collected = [
    profile.AIname && ["Assistant name", profile.AIname],
    profile.UserName && ["Your name", profile.UserName],
    profile.Usergmail && ["Gmail address", profile.Usergmail],
    onboarding.HelpRequest && ["First task idea", onboarding.HelpRequest],
    googleKnown && ["Google/Gmail account", hasGoogleAccount ? "Has an account" : "Doesn't use one"],
  ].filter(Boolean);
  const remaining = [
    !profile.AIname && "Choose an assistant name",
    !profile.UserName && "Share your name",
    !onboarding.HelpRequest && "Pick a first task when you're ready",
    !googleKnown && onboarding.Objectives?.GetGoogleUsage === "pending" && "Say whether you use a Google account",
    hasGoogleAccount && "Connect your Google account",
    onboarding.HelpRequest && `Do your first task: ${onboarding.HelpRequest}`,
  ].filter(Boolean);

  return <main className="completion-page"><section className="completion-panel">
    <span className="gate-eyebrow">PERSONA</span><h1>Convo ended</h1><div className="completion-columns"><div>
    <div className="completion-section"><h2>What has been collected</h2>
      {collected.length ? collected.map(([label, value]) => <p key={label}><span>{label}</span><strong>{value}</strong></p>) : <p>Nothing yet</p>}
    </div>
    <div className="completion-section"><h2>What still needs to be done</h2>
      {remaining.length ? remaining.map(item => <p key={item}>{item}</p>) : <p>Nothing right now</p>}
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="completion-actions"><button onClick={onReset} disabled={busy}>Reset conversation</button><button onClick={onLogout}>Sign out</button></div>
    </div><div className="completion-section transcript-section"><div className="transcript-heading"><h2>Full transcript</h2><button onClick={() => navigator.clipboard.writeText(transcript)} disabled={!transcript}>Copy transcript</button></div><pre>{transcript || "No saved messages"}</pre></div></div>
  </section></main>;
}

export default function Home() {
  const [signedIn, setSignedIn] = useState(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [conversation, setConversation] = useState(null);
  const [optimistic, setOptimistic] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [opening, setOpening] = useState(false);
  const [followingUp, setFollowingUp] = useState(false);
  const [closing, setClosing] = useState(false);
  const [callState, setCallState] = useState("idle");
  const [muted, setMuted] = useState(false);
  const [speaker, setSpeaker] = useState(true);
  const [seconds, setSeconds] = useState(0);
  const pcRef = useRef(null);
  const streamRef = useRef(null);
  const audioRef = useRef(null);
  const callIdRef = useRef(null);
  const callStateRef = useRef("idle");
  const openingRef = useRef(false);
  const pendingTextRef = useRef(null);
  const callAttemptRef = useRef(0);

  function setCall(value) { callStateRef.current = value; setCallState(value); }
  const refresh = useCallback(async () => {
    try {
      const next = await request("/conversation");
      setConversation(next);
      setOptimistic(current => current.filter(item => !next.messages.some(saved => saved.client_message_id === item.client_message_id)));
      setSignedIn(true);
    } catch (cause) {
      if (cause.message === "Sign in to continue") setSignedIn(false);
      else { setSignedIn(current => current === null ? false : current); setError(cause.message); }
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    if (!signedIn || !conversation || conversation.onboarding.onboarded || conversation.messages.length >= 3 || openingRef.current) return;
    openingRef.current = true;
    setOpening(true);
    request("/conversation/open", { method: "POST" }).then(setConversation).catch(cause => setError(cause.message)).finally(() => setOpening(false));
  }, [signedIn, conversation]);
  useEffect(() => {
    if (!signedIn || conversation?.onboarding?.onboarded) return;
    const timer = setInterval(refresh, opening ? 250 : callState === "active" ? 1000 : 3000);
    return () => clearInterval(timer);
  }, [signedIn, refresh, callState, opening, conversation?.onboarding?.onboarded]);
  useEffect(() => {
    if (callState !== "active") return;
    const timer = setInterval(() => setSeconds(value => value + 1), 1000);
    return () => clearInterval(timer);
  }, [callState]);
  useEffect(() => {
    if (conversation?.onboarding?.onboarded && callState !== "idle") hangup();
  }, [conversation?.onboarding?.onboarded, callState]);
  useEffect(() => {
    if (!closing) return;
    const timer = setTimeout(() => setClosing(false), 2500);
    return () => clearTimeout(timer);
  }, [closing]);

  async function login(event) {
    event.preventDefault(); setError(""); setBusy(true);
    try {
      await request("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ username, password }) });
      setPassword(""); await refresh();
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  }

  function cleanupCall() {
    callAttemptRef.current += 1;
    pcRef.current?.close(); pcRef.current = null;
    streamRef.current?.getTracks().forEach(track => track.stop()); streamRef.current = null;
    if (audioRef.current) audioRef.current.srcObject = null;
    callIdRef.current = null; setMuted(false); setSpeaker(true); setSeconds(0); setCall("idle");
  }

  async function hangup() {
    const callId = callIdRef.current;
    if (callId) setFollowingUp(true);
    cleanupCall();
    try {
      if (callId) {
        try { await request(`/calls/${encodeURIComponent(callId)}/hangup`, { method: "POST" }); }
        catch (cause) { setError(cause.message); }
      }
      await refresh();
    } finally {
      setFollowingUp(false);
    }
  }

  async function startCall() {
    if (callStateRef.current !== "idle") return;
    const attempt = ++callAttemptRef.current;
    setCall("connecting"); setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (attempt !== callAttemptRef.current) { stream.getTracks().forEach(track => track.stop()); return; }
      streamRef.current = stream;
      const pc = new RTCPeerConnection(); pcRef.current = pc;
      pc.ontrack = event => { if (audioRef.current) { audioRef.current.srcObject = event.streams[0]; audioRef.current.play().catch(() => {}); } };
      pc.onconnectionstatechange = () => {
        if (["failed", "disconnected", "closed"].includes(pc.connectionState) && callStateRef.current !== "idle") hangup();
      };
      stream.getTracks().forEach(track => pc.addTrack(track, stream));
      pc.createDataChannel("oai-events");
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      if (pc.iceGatheringState !== "complete") await new Promise(resolve => {
        const done = () => { clearTimeout(timeout); pc.removeEventListener("icegatheringstatechange", check); resolve(); };
        const check = () => { if (pc.iceGatheringState === "complete") done(); };
        const timeout = setTimeout(done, 8000);
        pc.addEventListener("icegatheringstatechange", check);
      });
      if (attempt !== callAttemptRef.current) return;
      const answer = await request("/calls/offer", { method: "POST", headers: { "Content-Type": "application/sdp" }, body: pc.localDescription.sdp });
      if (attempt !== callAttemptRef.current) {
        await request(`/calls/${encodeURIComponent(answer.call_id)}/hangup`, { method: "POST" }).catch(() => {});
        return;
      }
      callIdRef.current = answer.call_id;
      await pc.setRemoteDescription({ type: "answer", sdp: answer.sdp });
      await request(`/calls/${encodeURIComponent(answer.call_id)}/ready`, { method: "POST" });
      if (attempt !== callAttemptRef.current) return;
      setCall("active");
    } catch (cause) {
      if (attempt === callAttemptRef.current) { setError(cause.message); await hangup(); }
    }
  }

  async function send(text) {
    setError("");
    if (!pendingTextRef.current || pendingTextRef.current.text !== text) {
      pendingTextRef.current = { text, id: crypto.randomUUID() };
    }
    const body = JSON.stringify({ client_message_id: pendingTextRef.current.id, text });
    const clientMessageId = pendingTextRef.current.id;
    const callId = callIdRef.current;
    setBusy(true);
    setOptimistic(current => current.some(item => item.client_message_id === clientMessageId) ? current :
      [...current, { id: `pending:${clientMessageId}`, client_message_id: clientMessageId, role: "user", modality: "text", content: text }]);
    try {
      if (callId) {
        await request(`/calls/${encodeURIComponent(callId)}/text`, { method: "POST", headers: { "Content-Type": "application/json" }, body });
        refresh();
      } else {
        const next = await request("/message", { method: "POST", headers: { "Content-Type": "application/json" }, body });
        if (next.onboarding.onboarded) setClosing(true);
        setConversation(next);
        setOptimistic(current => current.filter(item => !next.messages.some(saved => saved.client_message_id === item.client_message_id)));
      }
      pendingTextRef.current = null;
      return true;
    } catch (cause) {
      setError(cause.message);
      await refresh();
      setOptimistic(current => current.filter(item => item.client_message_id !== clientMessageId));
      return false;
    }
    finally { setBusy(false); }
  }

  function mute(value) { streamRef.current?.getAudioTracks().forEach(track => { track.enabled = !value; }); setMuted(value); }

  async function logout() { await hangup(); await request("/auth/logout", { method: "POST" }); setConversation(null); setOptimistic([]); setSignedIn(false); }

  async function resetConversation() {
    setError(""); setBusy(true);
    cleanupCall();
    try {
      const next = await request("/conversation/reset", { method: "POST" });
      pendingTextRef.current = null;
      setOptimistic([]);
      openingRef.current = false;
      setOpening(false);
      setClosing(false);
      setConversation(next);
    } catch (cause) { setError(cause.message); }
    finally { setBusy(false); }
  }

  useEffect(() => {
    const onUnload = () => {
      const callId = callIdRef.current;
      if (callId) fetch(`${API}/calls/${encodeURIComponent(callId)}/hangup`, { method: "POST", credentials: "include", keepalive: true }).catch(() => {});
      streamRef.current?.getTracks().forEach(track => track.stop());
    };
    window.addEventListener("pagehide", onUnload);
    return () => window.removeEventListener("pagehide", onUnload);
  }, []);

  if (signedIn === null) return <main className="gate"><p>Loading Persona…</p></main>;
  if (!signedIn) return <main className="gate"><form className="gate-card" onSubmit={login}>
    <span className="gate-eyebrow">PERSONA</span><h1>Sign in</h1><p>Sign in to continue.</p>
    <label>Username<input autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} required /></label>
    <label>Password<input type="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required /></label>
    {error && <p className="error" role="alert">{error}</p>}<button className="gate-submit" disabled={busy}>{busy ? "Signing in…" : "Continue"}</button>
  </form></main>;
  if (conversation?.onboarding?.onboarded && callState === "idle" && !busy && !closing) return <CompletionScreen conversation={conversation} onReset={resetConversation} onLogout={logout} busy={busy} error={error} />;

  const messages = [...(conversation?.messages || []), ...optimistic];
  return <main className="preview-app"><div className="preview-stage"><div className="phone-shell">
    <IMessageFrame incoming={conversation?.call_invitation} speaker={speaker} onSpeaker={setSpeaker} name={conversation?.profile?.AIname} messages={messages} onSend={send} onCall={startCall} onHangup={hangup} onMute={mute} callState={callState} muted={muted} typing={(opening || busy || followingUp) && callState === "idle"} seconds={seconds} disabled={callState === "connecting" || opening} sending={busy} />
  </div><div className="app-meta"><span>PERSONA</span><h1>{conversation?.profile?.AIname || "Your assistant"}</h1><p>Your personal assistant.</p>{error && <p className="error" role="alert">{error}</p>}<div className="test-controls"><strong>Test controls</strong><button onClick={resetConversation} disabled={busy}>Reset conversation</button></div><button className="logout" onClick={logout}>Sign out</button></div></div><audio ref={audioRef} autoPlay playsInline muted={!speaker} /></main>;
}
