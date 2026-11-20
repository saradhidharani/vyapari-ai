export const dictationLanguages = [
  ["en-IN", "English (India)"],
  ["hi-IN", "हिन्दी"],
  ["te-IN", "తెలుగు"],
  ["en-US", "English (US)"],
];

export function getLocalRecognition(browser) {
  return [browser.SpeechRecognition, browser.webkitSpeechRecognition].find(
    (Recognition) =>
      typeof Recognition === "function"
      && "processLocally" in Recognition.prototype
      && typeof Recognition.available === "function"
  );
}

export function localRecognitionOptions(locale) {
  return { langs: [locale], processLocally: true };
}

export async function checkLocalRecognition(Recognition, locale) {
  const locales = locale === "hi-IN" || locale === "te-IN" ? [locale, locale.split("-")[0]] : [locale];
  let installable;
  for (const candidate of locales) {
    const status = await Recognition.available(localRecognitionOptions(candidate));
    if (status === "available") return { status, locale: candidate };
    if (!installable && (status === "downloadable" || status === "downloading")) {
      installable = { status, locale: candidate };
    }
  }
  return installable ?? { status: "unavailable", locale };
}

export function createLocalRecognition(Recognition, locale) {
  const recognition = new Recognition();
  recognition.processLocally = true;
  if (recognition.processLocally !== true) {
    throw new Error("This browser could not enable on-device speech recognition.");
  }
  recognition.lang = locale;
  recognition.continuous = false;
  recognition.interimResults = false;
  return recognition;
}

export function finalTranscript(event) {
  return Array.from(event.results)
    .slice(event.resultIndex)
    .filter((result) => result.isFinal)
    .map((result) => result[0]?.transcript.trim())
    .filter(Boolean)
    .join(" ");
}
