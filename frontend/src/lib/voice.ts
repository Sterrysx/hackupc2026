/**
 * useVoiceCapture — wraps the browser's `MediaRecorder` lifecycle and the
 * `/stt/transcribe` round-trip into a small state machine the UI can drive.
 *
 *   idle  ─► recording  (user taps mic, getUserMedia + MediaRecorder.start)
 *   recording  ─► transcribing  (user taps stop, blob assembled & uploaded)
 *   transcribing  ─► idle  (text returned, onTranscript fired)
 *   any  ─► error  (auto-clears back to idle after a short window)
 *
 * Cleanup notes:
 *   • Track stops + recorder stops on unmount (so closing the chat overlay
 *     while recording doesn't keep the mic hot).
 *   • If the recorded blob is empty (sub-50 ms taps), we silently return
 *     to idle without hitting the backend.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { transcribeAudio } from "@/lib/agentApi";

export type VoiceState = "idle" | "recording" | "transcribing" | "error";

export interface UseVoiceCaptureOptions {
  onTranscript: (text: string) => void;
  onError?: (message: string) => void;
}

interface VoiceCapture {
  state: VoiceState;
  errorMessage: string | null;
  isSupported: boolean;
  start: () => Promise<void>;
  stop: () => void;
  toggle: () => Promise<void>;
}

/** Pick the best MediaRecorder mime the current browser supports. */
function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/ogg;codecs=opus",
    "audio/ogg",
    "audio/mp4",
  ];
  for (const t of candidates) {
    try {
      if (MediaRecorder.isTypeSupported(t)) return t;
    } catch {
      /* some envs throw on unknown */
    }
  }
  return undefined;
}

function extensionFor(mime: string): string {
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("mp4")) return "m4a";
  if (mime.includes("wav")) return "wav";
  return "webm";
}

export function useVoiceCapture(opts: UseVoiceCaptureOptions): VoiceCapture {
  const [state, setState] = useState<VoiceState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const mimeRef = useRef<string | undefined>(undefined);
  const errorTimerRef = useRef<number | null>(null);
  // Latest callbacks — avoids stale closures inside long-lived recorder handlers.
  const onTranscriptRef = useRef(opts.onTranscript);
  const onErrorRef = useRef(opts.onError);
  useEffect(() => {
    onTranscriptRef.current = opts.onTranscript;
    onErrorRef.current = opts.onError;
  }, [opts.onTranscript, opts.onError]);

  const isSupported =
    typeof window !== "undefined" &&
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== "undefined";

  const cleanupStream = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => {
    return () => {
      try {
        recorderRef.current?.stop();
      } catch {
        /* noop */
      }
      cleanupStream();
      if (errorTimerRef.current !== null) window.clearTimeout(errorTimerRef.current);
    };
  }, [cleanupStream]);

  const failWith = useCallback(
    (msg: string) => {
      setErrorMessage(msg);
      setState("error");
      onErrorRef.current?.(msg);
      cleanupStream();
      if (errorTimerRef.current !== null) window.clearTimeout(errorTimerRef.current);
      errorTimerRef.current = window.setTimeout(() => {
        setState((s) => (s === "error" ? "idle" : s));
        setErrorMessage(null);
        errorTimerRef.current = null;
      }, 2400);
    },
    [cleanupStream],
  );

  const start = useCallback(async () => {
    if (!isSupported) {
      failWith("Voice capture not supported in this browser.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const mime = pickMimeType();
      mimeRef.current = mime;
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onerror = () => failWith("Recording failed.");
      recorder.onstop = async () => {
        const audioMime = mimeRef.current ?? recorder.mimeType ?? "audio/webm";
        const blob = new Blob(chunksRef.current, { type: audioMime });
        cleanupStream();
        if (blob.size < 600) {
          // Tiny tap → nothing meaningful to transcribe.
          setState("idle");
          return;
        }
        setState("transcribing");
        try {
          const ext = extensionFor(audioMime);
          const file = new File([blob], `aether-voice.${ext}`, { type: audioMime });
          const text = await transcribeAudio(file);
          if (text) onTranscriptRef.current(text);
          setState("idle");
        } catch (err) {
          const msg = err instanceof Error ? err.message : "Transcription failed.";
          failWith(msg);
        }
      };

      recorder.start();
      recorderRef.current = recorder;
      setState("recording");
      setErrorMessage(null);
    } catch (err) {
      const name = (err as DOMException | undefined)?.name;
      if (name === "NotAllowedError" || name === "PermissionDeniedError") {
        failWith("Microphone access denied.");
      } else if (name === "NotFoundError" || name === "DevicesNotFoundError") {
        failWith("No microphone detected.");
      } else {
        failWith("Could not start recording.");
      }
    }
  }, [cleanupStream, failWith, isSupported]);

  const stop = useCallback(() => {
    try {
      if (recorderRef.current && recorderRef.current.state !== "inactive") {
        recorderRef.current.stop();
      }
    } catch {
      /* noop */
    }
    recorderRef.current = null;
  }, []);

  const toggle = useCallback(async () => {
    if (state === "recording") stop();
    else if (state === "idle" || state === "error") await start();
  }, [start, state, stop]);

  return { state, errorMessage, isSupported, start, stop, toggle };
}
