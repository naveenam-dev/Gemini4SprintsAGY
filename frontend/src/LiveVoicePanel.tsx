import { useEffect, useRef, useState } from "react";
import { Mic, MicOff, PhoneOff, Radio, Send } from "lucide-react";
import type { LanguageCode } from "./types";

interface Props {
  planId: string;
  language: LanguageCode;
  languageName: string;
}

interface CaptionEntry {
  role: "user" | "assistant";
  text: string;
}

function downsampleTo16k(input: Float32Array, inputRate: number): Int16Array {
  if (inputRate === 16000) {
    const out = new Int16Array(input.length);
    for (let i = 0; i < input.length; i++) {
      const s = Math.max(-1, Math.min(1, input[i]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out;
  }
  const ratio = inputRate / 16000;
  const newLength = Math.round(input.length / ratio);
  const result = new Int16Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio);
    let accum = 0;
    let count = 0;
    for (let i = offsetBuffer; i < nextOffsetBuffer && i < input.length; i++) {
      accum += input[i];
      count++;
    }
    const sample = count > 0 ? accum / count : 0;
    const clamped = Math.max(-1, Math.min(1, sample));
    result[offsetResult] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
    offsetResult++;
    offsetBuffer = nextOffsetBuffer;
  }
  return result;
}

function int16ToBase64(pcm: Int16Array): string {
  const bytes = new Uint8Array(pcm.buffer);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function base64ToFloat32(b64: string): Float32Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  const int16 = new Int16Array(bytes.buffer);
  const float32 = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) {
    float32[i] = int16[i] / 0x8000;
  }
  return float32;
}

export default function LiveVoicePanel({ planId, language, languageName }: Props) {
  const [status, setStatus] = useState<"idle" | "connecting" | "ready" | "error">("idle");
  const [micActive, setMicActive] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [captions, setCaptions] = useState<CaptionEntry[]>([]);
  const [liveText, setLiveText] = useState("");

  const wsRef = useRef<WebSocket | null>(null);
  const playCtxRef = useRef<AudioContext | null>(null);
  const nextPlayTimeRef = useRef<number>(0);
  const activeSourcesRef = useRef<AudioBufferSourceNode[]>([]);

  const micStreamRef = useRef<MediaStream | null>(null);
  const micCtxRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);

  const stopPlaybackQueue = () => {
    activeSourcesRef.current.forEach((src) => {
      try {
        src.stop();
      } catch {
        // ignore
      }
    });
    activeSourcesRef.current = [];
    if (playCtxRef.current) {
      nextPlayTimeRef.current = playCtxRef.current.currentTime;
    }
  };

  const stopMic = () => {
    processorRef.current?.disconnect();
    processorRef.current = null;
    micCtxRef.current?.close().catch(() => {});
    micCtxRef.current = null;
    micStreamRef.current?.getTracks().forEach((t) => t.stop());
    micStreamRef.current = null;
    setMicActive(false);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "audio_stream_end" }));
    }
  };

  const disconnect = () => {
    stopMic();
    stopPlaybackQueue();
    wsRef.current?.close();
    wsRef.current = null;
    playCtxRef.current?.close().catch(() => {});
    playCtxRef.current = null;
    setStatus("idle");
  };

  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [planId]);

  const schedulePcm24k = (b64: string, sampleRate: number) => {
    if (!playCtxRef.current) {
      playCtxRef.current = new AudioContext({ sampleRate });
      nextPlayTimeRef.current = playCtxRef.current.currentTime;
    }
    const ctx = playCtxRef.current;
    if (ctx.state === "suspended") {
      ctx.resume().catch(() => {});
    }
    const samples = base64ToFloat32(b64);
    const buffer = ctx.createBuffer(1, samples.length, sampleRate);
    buffer.getChannelData(0).set(samples);

    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(ctx.destination);
    const startAt = Math.max(ctx.currentTime + 0.02, nextPlayTimeRef.current);
    src.start(startAt);
    nextPlayTimeRef.current = startAt + buffer.duration;
    activeSourcesRef.current.push(src);
    src.onended = () => {
      activeSourcesRef.current = activeSourcesRef.current.filter((s) => s !== src);
    };
  };

  const appendCaption = (role: "user" | "assistant", chunk: string) => {
    setCaptions((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.role === role) {
        return [...prev.slice(0, -1), { role, text: last.text + chunk }];
      }
      return [...prev, { role, text: chunk }];
    });
  };

  const connectLive = () => {
    setErrorMsg(null);
    setCaptions([]);
    setStatus("connecting");

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${proto}//${window.location.host}/ws/live/${planId}?language=${language}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.type === "ready") {
        setStatus("ready");
      } else if (msg.type === "audio") {
        schedulePcm24k(msg.data, msg.sample_rate || 24000);
      } else if (msg.type === "input_transcript") {
        appendCaption("user", msg.text);
      } else if (msg.type === "output_transcript") {
        appendCaption("assistant", msg.text);
      } else if (msg.type === "interrupted") {
        stopPlaybackQueue();
      } else if (msg.type === "error") {
        setErrorMsg(msg.message);
        setStatus("error");
      }
    };

    ws.onerror = () => {
      setErrorMsg("Live voice connection failed.");
      setStatus("error");
    };

    ws.onclose = () => {
      stopMic();
      setStatus((prev) => (prev === "error" ? "error" : "idle"));
    };
  };

  const toggleMic = async () => {
    if (micActive) {
      stopMic();
      return;
    }
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
      });
      micStreamRef.current = stream;
      const ctx = new AudioContext();
      micCtxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const processor = ctx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
        const floatData = e.inputBuffer.getChannelData(0);
        const pcm16 = downsampleTo16k(floatData, ctx.sampleRate);
        wsRef.current.send(
          JSON.stringify({
            type: "audio",
            data: int16ToBase64(pcm16),
          })
        );
      };

      source.connect(processor);
      processor.connect(ctx.destination);
      setMicActive(true);
    } catch {
      setErrorMsg("Microphone permission denied or unavailable. You can type below in Live mode.");
    }
  };

  const sendLivePrompt = () => {
    if (!liveText.trim() || wsRef.current?.readyState !== WebSocket.OPEN) return;
    const text = liveText.trim();
    setLiveText("");
    setCaptions((prev) => [...prev, { role: "user", text }]);
    wsRef.current.send(JSON.stringify({ type: "text", text }));
  };

  return (
    <div className="card" style={{ marginBottom: 16, borderColor: "#99d5cb" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <div>
          <h3 className="section-title" style={{ marginBottom: 2 }}>
            <Radio size={18} color="#0b6e63" /> Gemini Live Voice ({languageName})
          </h3>
          <p className="muted" style={{ margin: 0, fontSize: "0.82rem" }}>
            Real-time bidirectional audio over WebSocket (`gemini-3.8-live`)
          </p>
        </div>

        {status === "idle" || status === "error" ? (
          <button type="button" className="btn btn-primary" onClick={connectLive}>
            <Mic size={16} /> Start Live Voice
          </button>
        ) : (
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              className={`btn ${micActive ? "btn-danger" : "btn-primary"}`}
              disabled={status !== "ready"}
              onClick={toggleMic}
            >
              {micActive ? <MicOff size={16} /> : <Mic size={16} />}
              {micActive ? "Mute Mic" : "Speak"}
            </button>
            <button type="button" className="btn btn-secondary" onClick={disconnect}>
              <PhoneOff size={16} /> End
            </button>
          </div>
        )}
      </div>

      {status === "connecting" && (
        <p className="muted" style={{ marginTop: 10, marginBottom: 0 }}>
          Connecting to Gemini 3.8 Live...
        </p>
      )}
      {errorMsg && (
        <div className="alert-box warning" style={{ marginTop: 10, marginBottom: 0 }}>
          {errorMsg}
        </div>
      )}

      {status === "ready" && (
        <div style={{ marginTop: 12 }}>
          <div
            style={{
              background: "#f8fafc",
              border: "1px solid var(--border)",
              borderRadius: 10,
              padding: 10,
              maxHeight: 160,
              overflowY: "auto",
              marginBottom: 8,
              fontSize: "0.86rem",
            }}
          >
            {captions.length === 0 ? (
              <span className="muted">
                Connected. Tap <strong>Speak</strong> (headphones recommended) or send a quick prompt to hear spoken guidance.
              </span>
            ) : (
              captions.map((c, idx) => (
                <div key={idx} style={{ marginBottom: 6 }}>
                  <strong style={{ color: c.role === "user" ? "#0b6e63" : "#1e293b" }}>
                    {c.role === "user" ? "Family: " : "Discharge Dost: "}
                  </strong>
                  <span>{c.text}</span>
                </div>
              ))
            )}
          </div>

          <div style={{ display: "flex", gap: 8 }}>
            <input
              className="input"
              value={liveText}
              onChange={(e) => setLiveText(e.target.value)}
              placeholder="Or type to speak back via Gemini Live..."
              onKeyDown={(e) => {
                if (e.key === "Enter") sendLivePrompt();
              }}
            />
            <button
              type="button"
              className="btn btn-secondary"
              disabled={!liveText.trim()}
              onClick={sendLivePrompt}
              aria-label="Send to live session"
            >
              <Send size={15} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
