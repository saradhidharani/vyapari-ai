import React, { useEffect, useState } from "react";
import { duplicateWebsite, renameWebsite, setWebsiteArchived } from "./api";

export default function WebsiteLifecycle({
  selected, archived, busy, setBusy, canLeaveWebsite, onChange,
}) {
  const [form, setForm] = useState(null);
  const [feedback, setFeedback] = useState(null);

  useEffect(() => {
    setForm(null);
  }, [selected?.id]);

  async function saveName(event) {
    event.preventDefault();
    if (busy || !form?.label.trim()) return;
    const duplicate = form.action === "duplicate";
    if (duplicate && !canLeaveWebsite()) return;

    setBusy(true);
    setFeedback(null);
    try {
      const save = duplicate ? duplicateWebsite : renameWebsite;
      const updated = await save(selected.id, form.label.trim());
      setForm(null);
      onChange(updated, form.action);
      setFeedback({ message: duplicate ? "Draft duplicated." : "Website renamed." });
    } catch (error) {
      setFeedback({ message: error.message, error: true });
    } finally {
      setBusy(false);
    }
  }

  async function archive(site, archived) {
    if (busy) return;
    if (archived) {
      const message = site.published
        ? `Archive "${site.label}" and take down its published link?`
        : `Archive "${site.label}"?`;
      if (!window.confirm(message) || !canLeaveWebsite()) return;
    }
    setBusy(true);
    setFeedback(null);
    try {
      const updated = await setWebsiteArchived(site.id, archived);
      setForm(null);
      onChange(updated, archived ? "archive" : "restore");
      setFeedback({ message: archived ? "Website archived." : "Website restored as a draft." });
    } catch (error) {
      setFeedback({ message: error.message, error: true });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      {selected && (
        <div className="website-lifecycle-actions">
          <button className="secondary" type="button" disabled={busy} onClick={() => {
            setFeedback(null);
            setForm({ action: "rename", label: selected.label });
          }}>Rename website</button>
          <button className="secondary" type="button" disabled={busy} onClick={() => {
            setFeedback(null);
            setForm({ action: "duplicate", label: `${selected.label.slice(0, 93)} (copy)` });
          }}>Duplicate draft</button>
          <button className="secondary" type="button" disabled={busy} onClick={() => archive(selected, true)}>
            Archive website
          </button>
        </div>
      )}
      {selected && form && (
        <form className="workspace-form" onSubmit={saveName}>
          <label>
            {form.action === "duplicate" ? "Name for the copy" : "Website name"}
            <input
              value={form.label}
              required
              maxLength={100}
              disabled={busy}
              onChange={(event) => setForm({ ...form, label: event.target.value })}
            />
          </label>
          <button className="primary" disabled={busy || !form.label.trim()}>
            {form.action === "duplicate" ? "Copy saved draft" : "Save website name"}
          </button>
          <button className="secondary" type="button" disabled={busy} onClick={() => setForm(null)}>Cancel</button>
        </form>
      )}
      {archived.length > 0 && (
        <section className="archived-websites">
          <h4>Archived websites</h4>
          {archived.map((site) => (
            <div className="setting-row" key={site.id}>
              <strong>{site.label}</strong>
              <button className="secondary" type="button" disabled={busy} onClick={() => archive(site, false)}>
                Restore
              </button>
            </div>
          ))}
        </section>
      )}
      {feedback && <p role={feedback.error ? "alert" : "status"}>{feedback.message}</p>}
    </>
  );
}
