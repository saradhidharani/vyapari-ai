import React, { useRef, useState } from "react";
import { sendWebsiteInquiry } from "./api";

export default function StorefrontInquiryForm({ slug, accentColor }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const latest = useRef(null);

  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const data = Object.fromEntries(
      [...new FormData(form)].map(([key, value]) => [key, value.trim()])
    );
    setError("");
    setSent(false);
    if (!data.email && !data.phone) {
      setError("Enter an email address or phone number so the business can reply.");
      return;
    }

    setBusy(true);
    try {
      const content = JSON.stringify(data);
      if (latest.current?.content !== content) {
        latest.current = { content, id: crypto.randomUUID() };
      }
      await sendWebsiteInquiry(slug, { ...data, request_id: latest.current.id });
      latest.current = null;
      form.reset();
      setSent(true);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="storefront-enquiry" aria-labelledby="enquiry-title">
      <h2 id="enquiry-title">Contact us</h2>
      <p>Leave a message and an email address or phone number so the business can reply.</p>
      <form onSubmit={submit}>
        <fieldset disabled={busy}>
          <label>Name<input name="name" autoComplete="name" required maxLength={100} /></label>
          <label>Email<input name="email" type="email" autoComplete="email" maxLength={254} /></label>
          <label>Phone<input name="phone" type="tel" autoComplete="tel" maxLength={40} /></label>
          <label>Message<textarea name="message" required maxLength={1000} rows={4} /></label>
          <button className="primary" type="submit" style={{ background: accentColor }}>
            {busy ? "Sending…" : "Send enquiry"}
          </button>
        </fieldset>
      </form>
      {sent && <p role="status">Your enquiry was sent to the business.</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
