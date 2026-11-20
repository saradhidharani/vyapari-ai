import React, { useEffect, useState } from "react";
import { createTeamInvitation, listTeamInvitations, revokeTeamInvitation } from "./api";
import { assignableWorkspaceRoles, workspaceRoleLabels } from "./workspaceRoles";

export default function TeamInvitations() {
  const [invitations, setInvitations] = useState(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("sales");
  const [link, setLink] = useState(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listTeamInvitations(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setInvitations(data);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    return () => controller.abort();
  }, [attempt]);

  async function createLink(event) {
    event.preventDefault();
    if (busy || !email.trim()) return;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const { token, ...invite } = await createTeamInvitation(email.trim(), role);
      setInvitations((previous) => [invite, ...previous.filter((item) => item.email !== invite.email)]);
      setLink({ id: invite.id, url: `${window.location.origin}/#invite=${token}` });
      setEmail("");
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  async function revoke(invite) {
    if (busy || !window.confirm(`Revoke the invitation for ${invite.email}?`)) return;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      await revokeTeamInvitation(invite.id);
      setInvitations((previous) => previous.filter((item) => item.id !== invite.id));
      setLink((current) => current?.id === invite.id ? null : current);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(link.url);
      setStatus("Invitation link copied.");
    } catch {
      setStatus("Select the link and copy it.");
    }
  }

  return (
    <section className="panel settings-panel workspace-settings">
      <h3>Invite staff</h3>
      <p>Create a single-use link and share it privately with the invited email’s owner. Links expire after seven days.</p>
      {invitations && (
        <form className="workspace-form" onSubmit={createLink}>
          <label>
            Staff email
            <input type="email" required maxLength={254} value={email} disabled={busy} onChange={(event) => setEmail(event.target.value)} />
          </label>
          <label>
            Role
            <select value={role} disabled={busy} onChange={(event) => setRole(event.target.value)}>
              {assignableWorkspaceRoles.map((role) => <option key={role} value={role}>{workspaceRoleLabels[role]}</option>)}
            </select>
          </label>
          <button className="primary" disabled={busy || !email.trim()}>Create invitation link</button>
        </form>
      )}
      {link && (
        <div className="workspace-form">
          <label>
            Invitation link
            <input readOnly value={link.url} onFocus={(event) => event.target.select()} />
          </label>
          <button className="secondary" type="button" onClick={copyLink}>Copy link</button>
        </div>
      )}
      {status && <p role="status">{status}</p>}
      {error && <p role="alert">{error}</p>}
      {!invitations && !error && <p role="status">Loading invitations…</p>}
      {!invitations && error && <button className="secondary" onClick={() => {
        setError("");
        setAttempt((previous) => previous + 1);
      }}>Retry</button>}
      {invitations?.length === 0 && <p>No pending invitations.</p>}
      {invitations?.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Email</th><th>Role</th><th>Expires</th><th>Actions</th></tr></thead>
            <tbody>
              {invitations.map((invite) => (
                <tr key={invite.id}>
                  <td>{invite.email}</td>
                  <td>{workspaceRoleLabels[invite.role]}</td>
                  <td>{new Date(invite.expires_at * 1000).toLocaleDateString("en-IN")}</td>
                  <td><button className="secondary" type="button" disabled={busy} onClick={() => revoke(invite)}>Revoke</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
