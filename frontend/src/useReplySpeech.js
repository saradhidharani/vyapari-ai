import { useEffect, useRef, useState } from "react";

const voiceLanguages = {
  en: { name: "English", locale: "en-IN" },
  hi: { name: "Hindi", locale: "hi-IN" },
  te: { name: "Telugu", locale: "te-IN" },
};

export function selectLocalVoice(voices, language) {
  const { locale } = voiceLanguages[language];
  const matching = voices.filter((voice) =>
    voice.localService === true && voice.lang.toLowerCase().split("-")[0] === language
  );
  return matching.find((voice) => voice.lang.toLowerCase() === locale.toLowerCase())
    ?? matching.find((voice) => voice.default)
    ?? matching[0];
}

export default function useReplySpeech(active) {
  const current = useRef(null);
  const [playback, setPlayback] = useState(null);

  useEffect(() => {
    if (!active) return;
    const synth = window.speechSynthesis;
    synth?.getVoices();
    return () => {
      if (current.current) {
        current.current = null;
        synth?.cancel();
      }
      setPlayback(null);
    };
  }, [active]);

  function stopReading() {
    if (current.current) {
      current.current = null;
      window.speechSynthesis.cancel();
    }
    setPlayback(null);
  }

  function listen(index, text, language) {
    const synth = window.speechSynthesis;
    const stop = current.current?.index === index;
    stopReading();
    if (stop) return;
    if (!synth || !window.SpeechSynthesisUtterance) {
      setPlayback({ index, error: "Read aloud is unavailable in this browser." });
      return;
    }

    const voice = selectLocalVoice(synth.getVoices(), language);
    if (!voice) {
      setPlayback({ index, error: `No local ${voiceLanguages[language].name} voice is available on this device.` });
      return;
    }

    const utterance = new window.SpeechSynthesisUtterance(text);
    utterance.voice = voice;
    utterance.lang = voice.lang;
    current.current = { index, utterance };
    setPlayback({ index, error: "" });

    function finish(error = "") {
      if (current.current?.utterance !== utterance) return;
      current.current = null;
      setPlayback(error ? { index, error } : null);
    }

    utterance.onend = () => finish();
    utterance.onerror = () => finish("Could not play this reply. Try again.");
    try {
      synth.speak(utterance);
    } catch {
      finish("Could not play this reply. Try again.");
    }
  }

  return { listen, playback, stopReading };
}
