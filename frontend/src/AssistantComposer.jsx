import React, { useEffect, useRef, useState } from "react";
import { Mic, Send, Square } from "lucide-react";
import {
  checkLocalRecognition,
  createLocalRecognition,
  dictationLanguages,
  finalTranscript,
  getLocalRecognition,
  localRecognitionOptions,
} from "./localDictation";

const recognitionErrors = {
  "not-allowed": "Microphone permission was denied.",
  "service-not-allowed": "On-device dictation was blocked by the browser.",
  "audio-capture": "The browser could not access a microphone.",
  "no-speech": "No speech was detected. Try again.",
  "language-not-supported": "This language is unavailable for on-device dictation.",
};

export default function AssistantComposer({
  message, setMessage, disabled, onSubmit, onStartDictation, onListeningChange,
}) {
  const Recognition = getLocalRecognition(window);
  // Opt-in fallback: the browser's own speech service (supports Hindi and Telugu in Chrome and Edge).
  const CloudRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const [cloud, setCloud] = useState(false);
  const [locale, setLocale] = useState("en-IN");
  const [capability, setCapability] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [installing, setInstalling] = useState(false);
  const [recording, setRecording] = useState("");
  const [error, setError] = useState("");
  const currentRecognition = useRef(null);
  const currentInstallation = useRef(null);
  const secureContext = window.isSecureContext !== false;
  const availability = capability?.status;

  useEffect(() => {
    if (!Recognition || !secureContext) return;
    let active = true;
    checkLocalRecognition(Recognition, locale)
      .then((result) => {
        if (active) setCapability(result);
      })
      .catch(() => {
        if (active) setCapability({ status: "blocked", locale });
      });
    return () => { active = false; };
  }, [Recognition, secureContext, locale, attempt]);

  useEffect(() => () => {
    const recognition = currentRecognition.current;
    currentRecognition.current = null;
    currentInstallation.current = null;
    if (recognition) {
      recognition.abort();
      onListeningChange(false);
    }
  }, [onListeningChange]);

  useEffect(() => {
    if (disabled && currentRecognition.current) {
      const recognition = currentRecognition.current;
      currentRecognition.current = null;
      recognition.abort();
      setRecording("");
      onListeningChange(false);
    }
  }, [disabled, onListeningChange]);

  function checkAvailability() {
    setCapability(null);
    setAttempt((previous) => previous + 1);
  }

  async function installLanguage() {
    const request = {};
    const options = localRecognitionOptions(capability.locale);
    currentInstallation.current = request;
    setInstalling(true);
    setError("");
    try {
      const installed = await Recognition.install(options);
      if (currentInstallation.current !== request) return;
      if (installed) checkAvailability();
      else setError("The browser could not install the language pack.");
    } catch {
      if (currentInstallation.current === request) {
        setError("The browser could not install the language pack.");
      }
    } finally {
      if (currentInstallation.current === request) {
        currentInstallation.current = null;
        setInstalling(false);
      }
    }
  }

  function toggleDictation() {
    if (currentRecognition.current) {
      try {
        currentRecognition.current.stop();
        setRecording("stopping");
      } catch {
        setError("Could not stop dictation. Try again.");
      }
      return;
    }
    const useCloud = cloud && Boolean(CloudRecognition);
    if ((!useCloud && (!Recognition || availability !== "available")) || disabled) return;

    setError("");
    let recognition;
    let captured = false;
    function finish(message = "") {
      if (currentRecognition.current !== recognition) return;
      currentRecognition.current = null;
      setRecording("");
      onListeningChange(false);
      if (message) setError(message);
    }
    try {
      if (useCloud) {
        recognition = new CloudRecognition();
        recognition.lang = locale;
        recognition.continuous = false;
        recognition.interimResults = false;
      } else {
        recognition = createLocalRecognition(Recognition, capability.locale);
      }
      currentRecognition.current = recognition;
      recognition.onresult = (event) => {
        if (currentRecognition.current !== recognition) return;
        const transcript = finalTranscript(event);
        if (!transcript) return;
        captured = true;
        setMessage((previous) => [previous.trim(), transcript].filter(Boolean).join(" ").slice(0, 300));
      };
      recognition.onerror = (event) => {
        finish(recognitionErrors[event.error] ?? "On-device dictation could not finish. Try again.");
        if (event.error === "language-not-supported") checkAvailability();
      };
      recognition.onend = () => finish(captured ? "" : "No speech was detected. Try again.");
      onStartDictation();
      setRecording("listening");
      onListeningChange(true);
      recognition.start();
    } catch {
      if (recognition) finish("Could not start on-device dictation.");
      else setError("Could not enable on-device dictation.");
    }
  }

  const canInstall = availability === "downloadable" && typeof Recognition?.install === "function";
  const canRecord = (cloud && Boolean(CloudRecognition)) || availability === "available";
  const voiceNotice = !secureContext ? "Open Vyapari AI at http://localhost:5173 or over HTTPS to use the microphone."
    : cloud && CloudRecognition ? (recording === "listening" ? "Listening…" : recording === "stopping" ? "Finishing dictation…"
      : "Cloud speech is on: your browser sends the audio to its speech service to recognise it.")
    : !Recognition ? "This browser does not expose on-device dictation. You can still type your question."
    : recording === "listening" ? "Listening on this device…"
    : recording === "stopping" ? "Finishing dictation…"
    : installing ? "Installing the speech language pack…"
    : availability === "downloading" ? "The speech language pack is downloading."
    : canInstall ? "Install this language to dictate on this device."
    : availability === "blocked" ? "The browser blocked the on-device speech check. Open Vyapari AI in a regular browser tab and check again."
    : availability === "unavailable" ? `This browser has no on-device speech pack for ${dictationLanguages.find(([value]) => value === locale)[1]}. Choose another language or type your question.`
    : availability === "downloadable" ? "This browser reports a speech pack but cannot install it from this page."
    : !availability ? "Checking on-device dictation…"
    : "";

  return (
    <>
      <form className="chat-compose" onSubmit={(event) => {
        event.preventDefault();
        if (!disabled && !recording) onSubmit(message);
      }}>
        <input
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          maxLength={300}
          disabled={disabled}
          aria-label="Question for the assistant"
          placeholder="Ask about sales, stock, or orders…"
        />
        <button
          type="button"
          className="mic-button"
          aria-label={recording ? "Stop dictation" : "Start dictation"}
          title={recording ? "Stop dictation" : "Start dictation"}
          disabled={disabled || !canRecord || recording === "stopping"}
          onClick={toggleDictation}
        >
          {recording ? <Square size={18} /> : <Mic size={20} />}
        </button>
        <button
          type="submit"
          className="send-button"
          disabled={disabled || Boolean(recording) || !message.trim()}
          aria-label="Send question"
        >
          <Send size={19} />
        </button>
      </form>
      <div className="dictation-controls">
        {(Recognition || CloudRecognition) && secureContext && (
          <label>
            Dictation language
            <select value={locale} disabled={disabled || installing || Boolean(recording)} onChange={(event) => {
              setLocale(event.target.value);
              setCapability(null);
              setError("");
            }}>
              {dictationLanguages.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
        )}
        {CloudRecognition && secureContext && (
          <label>
            <input type="checkbox" checked={cloud} disabled={disabled || Boolean(recording)}
              onChange={(event) => { setCloud(event.target.checked); setError(""); }} />
            {" "}Use browser cloud speech (Hindi, Telugu)
          </label>
        )}
        {canInstall && !cloud && (
          <button className="secondary" type="button" disabled={disabled || installing} onClick={installLanguage}>
            Install language
          </button>
        )}
        {["downloading", "blocked", "unavailable"].includes(availability) && (
          <button className="secondary" type="button" disabled={disabled || installing} onClick={checkAvailability}>
            Check again
          </button>
        )}
        {voiceNotice && <span role="status">{voiceNotice}</span>}
        {error && <span role="alert">{error}</span>}
      </div>
    </>
  );
}
