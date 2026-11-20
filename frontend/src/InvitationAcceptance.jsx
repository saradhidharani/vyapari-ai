import React, { useEffect, useState } from "react";
import { acceptInvitation, previewInvitation, sendInvitationCode } from "./api";
import { workspaceRoleLabels } from "./workspaceRoles";

export default function InvitationAcceptance({ invite, onAccept, onCancel }) {
  const [preview, setPreview] = useState(null);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [codeNotice, setCodeNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    previewInvitation(invite, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setPreview(data);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [invite]);

  async function join(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      onAccept(await acceptInvitation(invite, password, preview.verification_required ? code : undefined));
    } catch (failure) {
      setError(failure.message);
      setBusy(false);
    }
  }

  async function sendCode() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const sent = await sendInvitationCode(invite);
      setCodeNotice(`We sent a code to ${sent.destination}. It expires in 10 minutes.`);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="modal-backdrop">
      <form className="modal" onSubmit={join}>
        <div className="modal-title"><h3>Join a business</h3></div>
        {loading && <p role="status">Checking your invitation…</p>}
        {preview && (
          <>
            <p>Join <strong>{preview.business_name}</strong> as {workspaceRoleLabels[preview.role]}.</p>
            {preview.role === "owner" && (
              <p>An agency set up this workspace for you. As the owner you control team access and can change or
                revoke the agency's access at any time in Settings → Agency access.</p>
            )}
            <label>
              Invited email
              <input type="email" autoComplete="username" value={preview.email} readOnly />
            </label>
            <label>
              {preview.existing_account ? "Your Vyapari password" : "Choose a password"}
              <input
                type="password"
                autoComplete={preview.existing_account ? "current-password" : "new-password"}
                required
                minLength={12}
                maxLength={128}
                value={password}
                disabled={busy}
                onChange={(event) => setPassword(event.target.value)}
              />
              {!preview.existing_account && <small>Use at least 12 characters.</small>}
            </label>
            {preview.verification_required && (
              <>
                <p>To join, confirm you can receive email at the invited address.</p>
                {!codeNotice ? (
                  <button className="secondary" type="button" disabled={busy} onClick={sendCode}>Send code</button>
                ) : (
                  <>
                    <p role="status">{codeNotice}</p>
                    <label>
                      6-digit code
                      <input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required
                        disabled={busy} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))} />
                    </label>
                    <button className="text-button" type="button" style={{ marginBottom: 12 }} disabled={busy} onClick={sendCode}>Send a new code</button>
                  </>
                )}
              </>
            )}
            <button className="primary" type="submit" disabled={busy || (preview.verification_required && !codeNotice)}>
              {busy ? "Joining…" : "Accept invitation"}
            </button>
          </>
        )}
        {error && <p role="alert">{error}</p>}
        <button className="text-button invitation-back" type="button" onClick={onCancel} disabled={busy}>Back to Vyapari AI</button>
      </form>
    </main>
  );
}
