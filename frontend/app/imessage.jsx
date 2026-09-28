"use client";

import { useEffect, useRef, useState } from "react";
import { App, Message, Messages } from "konsta/react";

function Icon({ name, size = 24 }) {
  const assets = {
    back: "chevron_left",
    chevron: "chevron_right",
    collapse: "chevron_down",
    phone: "phone_fill",
    hangup: "phone_down_fill",
    mic: "mic",
    micFill: "mic_fill",
    micMuted: "mic_slash_fill",
    video: "videocam",
    videoFill: "videocam_fill",
    plus: "plus",
    speaker: "speaker_3_fill",
    speakerMuted: "speaker_slash_fill",
    more: "ellipsis",
    wifi: "wifi",
    arrow: "arrow_up"
  };
  return <span className="ios-icon" style={{ width: size, height: size, maskImage: `url(/icons/ios/${assets[name]}.svg)` }} aria-hidden="true" />;
}

function Battery() {
  return <svg className="battery" width="29" height="15" viewBox="0 0 29 15" role="img" aria-label="Battery 67 percent">
    <rect x="0" y=".5" width="25" height="14" rx="4" fill="#66666b" />
    <path d="M4 .5H16.75V14.5H4A4 4 0 0 1 0 10.5V4.5A4 4 0 0 1 4 .5Z" fill="#f5f5f7" />
    <path d="M26.5 5v5c1.4-.3 2.2-1.2 2.2-2.5S27.9 5.3 26.5 5Z" fill="#8e8e93" />
    <text x="12.5" y="11.6" textAnchor="middle" fill="#09090b">67</text>
  </svg>;
}

function Avatar() {
  return <div className="avatar"><svg viewBox="0 0 48 48" fill="none" aria-hidden="true"><path d="M28 8c-9-8-23 20-18 28 5 8 20-9 21-20 1-7-3-9-3-8Zm0 0c10 9 18 29 10 32-5 2-11-6-14-11" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg></div>;
}

function MessageText({ text }) {
  return String(text).split(/(https?:\/\/[^\s]+)/g).map((part, index) =>
    /^https?:\/\//.test(part) ? <a key={index} href={part} target="_blank" rel="noreferrer">{part}</a> : part);
}

function dateLabel(value) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return null;
  const today = date.toDateString() === new Date().toDateString();
  return `${today ? "Today" : date.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ${date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

export function IMessageFrame({ name, messages, onSend, onCall, onHangup, onMute, callState, muted, typing, seconds, disabled, sending, incoming, speaker, onSpeaker }) {
  const [draft, setDraft] = useState("");
  const [subject, setSubject] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [clock, setClock] = useState("");
  const scrollRef = useRef(null);
  const inputRef = useRef(null);
  const pinnedRef = useRef(true);
  const active = callState === "active";
  const inCall = active || callState === "connecting";
  const ringing = incoming && !dismissed && !inCall;
  const islandMode = ringing ? "incoming" : inCall ? (expanded ? "expanded" : "compact") : "idle";
  const lastMessageId = messages.at(-1)?.id;
  const contact = name || "Persona";
  useEffect(() => {
    const update = () => setClock(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }));
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, []);
  useEffect(() => { if (!incoming) setDismissed(false); }, [incoming]);
  useEffect(() => { if (!inCall) setExpanded(false); }, [inCall]);
  useEffect(() => {
    if (scrollRef.current && pinnedRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [lastMessageId, typing]);
  const time = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
  async function submit(event) {
    event.preventDefault();
    const text = [subject.trim(), draft.trim()].filter(Boolean).join("\n");
    if (!text || disabled || sending) return;
    const previousDraft = draft;
    const previousSubject = subject;
    setDraft(""); setSubject("");
    if (inputRef.current) inputRef.current.style.height = "auto";
    pinnedRef.current = true;
    const sent = await onSend(text);
    if (sent === false) { setDraft(current => current || previousDraft); setSubject(current => current || previousSubject); }
  }
  function startCall() { setExpanded(false); onCall(); }
  return <App theme="ios" dark safeAreas={false} className="phone">
    <div className={`status-bar ${inCall ? "on-call" : ""}`}><time>{clock}</time><span className="status-icons"><svg className="signal" width="18" height="13" viewBox="0 0 18 13" role="img" aria-label="Cellular signal"><rect x="0" y="8" width="3" height="5" rx="1" /><rect x="5" y="5.5" width="3" height="7.5" rx="1" /><rect x="10" y="3" width="3" height="10" rx="1" /><rect x="15" width="3" height="13" rx="1" opacity=".35" /></svg><Icon name="wifi" size={18} /><Battery /></span></div>
    <section className={`dynamic-island ${islandMode}`} aria-label={ringing ? "Incoming call" : inCall ? "Call controls" : "Dynamic Island"} onKeyDown={event => { if (event.key === "Escape") setExpanded(false); }}>
      {islandMode === "compact" && <button className="island-compact" aria-label="Expand call controls" aria-expanded={false} onClick={() => setExpanded(true)}><span><Icon name="phone" size={15} />{active ? time : "Calling…"}</span><span className={`waveform ${active && !muted ? "moving" : ""}`} aria-hidden="true">{Array.from({ length: 16 }, (_, index) => <i key={index} style={{ "--i": index }} />)}</span></button>}
      {(ringing || (inCall && expanded)) && <div className="island-details">
        <div className="island-person"><Avatar /><div>{ringing && <span>Persona</span>}<strong>{contact}</strong>{!ringing && <span>{active ? time : "Connecting…"}</span>}</div>
          {!ringing && <button className="collapse-island" aria-label="Collapse call controls" onClick={() => setExpanded(false)}><Icon name="collapse" size={17} /></button>}
        </div>
        {ringing ? <div className="incoming-actions"><button className="call-button red" aria-label="Dismiss call invitation" onClick={() => setDismissed(true)}><Icon name="hangup" /></button><button className="call-button green" aria-label="Answer call" onClick={startCall}><Icon name="phone" /></button></div> : <div className="call-actions">
          <button className={`call-button ${speaker ? "selected" : ""}`} aria-label={speaker ? "Mute call audio" : "Unmute call audio"} aria-pressed={speaker} onClick={() => onSpeaker(!speaker)}><Icon name={speaker ? "speaker" : "speakerMuted"} /></button>
          <button className="call-button" aria-label="Video unavailable for voice calls" disabled><Icon name="videoFill" /><span className="slash" /></button>
          <button className={`call-button ${!muted ? "selected" : ""}`} aria-label={muted ? "Unmute microphone" : "Mute microphone"} aria-pressed={muted} onClick={() => onMute(!muted)} disabled={!active}><Icon name={muted ? "micMuted" : "micFill"} /></button>
          <button className="call-button" aria-label="Return to messages" onClick={() => setExpanded(false)}><Icon name="more" /></button>
          <button className="call-button red" aria-label="End call" onClick={onHangup}><Icon name="hangup" /></button>
        </div>}
      </div>}
      {inCall && <i className="status-privacy" />}
    </section>
    <header className="conversation-header">
      <span className="glass back-button" aria-hidden="true"><Icon name="back" size={23} /><span>{messages.length}</span></span>
      <strong className="contact-name">{contact}<Icon name="chevron" size={12} /></strong>
      <button className="glass video-button" aria-label={inCall ? "Show call controls" : "Start voice call"} onClick={inCall ? () => setExpanded(true) : startCall} disabled={!inCall && disabled}><Icon name="video" size={27} /></button>
    </header>
    <div className="conversation" ref={scrollRef} onScroll={event => { const el = event.currentTarget; pinnedRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48; }} role="log" aria-label="Messages" aria-live="polite"><Messages>
      {messages.map((message, index) => {
        const previous = messages[index - 1];
        const next = messages[index + 1];
        const label = clock ? dateLabel(message.created_at) : null;
        const separated = !previous || new Date(message.created_at) - new Date(previous.created_at) > 300000;
        const sent = message.role === "user";
        return <div className="message-group" key={message.id}>
          {label && separated && <div className="message-date">{label}</div>}
          <Message type={sent ? "sent" : "received"} className={`bubble ${sent ? "sent" : "received"} ${next?.role !== message.role ? "tail" : ""}`} text={<MessageText text={message.content} />} />
          {sent && !next && <div className="delivery-status">{String(message.id).startsWith("pending:") ? "Sending…" : "Delivered"}</div>}
        </div>;
      })}
      {typing && <div className="typing" aria-label={`${contact} is typing`}><i /><i /><i /></div>}
    </Messages></div>
    <form className="composer" onSubmit={submit}>
      <button className="glass add-button" type="button" aria-label="Message options unavailable" disabled><Icon name="plus" size={26} /></button>
      <div className="composer-fields">
        <input className="subject-input" aria-label="Subject" placeholder="Subject" value={subject} onChange={event => setSubject(event.target.value)} disabled={disabled} />
        <div className="message-input-row"><textarea ref={inputRef} rows={1} aria-label="Message" placeholder="iMessage" value={draft} onChange={event => { setDraft(event.target.value); event.target.style.height = "auto"; event.target.style.height = `${Math.min(event.target.scrollHeight, 110)}px`; }} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(event); } }} disabled={disabled} />
          {draft.trim() || subject.trim() ? <button className="send-button" type="submit" aria-label="Send message" disabled={disabled || sending}><Icon name="arrow" size={20} /></button> : <span className="composer-mic" aria-hidden="true"><Icon name="mic" size={23} /></span>}
        </div>
      </div>
    </form>
    <div className="home-indicator" aria-hidden="true" />
  </App>;
}
