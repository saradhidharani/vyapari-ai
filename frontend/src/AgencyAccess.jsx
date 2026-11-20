import React, { useEffect, useState } from "react";
import {
  grantAgencyAccess,
  listAgencyGrants,
  previewAgency,
  revokeAgencyAccess,
  updateAgencyAccess,
} from "./api";
import { assignableWorkspaceRoles, workspaceRoleLabels } from "./workspaceRoles";

function WebsiteScope({ websites, value, onChange, disabled }) {
  return (
    <fieldset className="website-catalog" disabled={disabled}>
      <legend>Websites the agency can edit</legend>
      <label className="website-picker">
        Scope
        <select value={value === null ? "all" : "assigned"} onChange={(event) => onChange(event.target.value === "all" ? null : [])}>
          <option value="all">All current and future websites</option>
          <option value="assigned">Selected websites only</option>
        </select>
      </label>
      {value !== null && (
        <div className="website-product-list">
          {!websites && <p role="status">Website list unavailable. Reload the page to try again.</p>}
          {websites?.length === 0 && <p>This business has no websites to choose.</p>}
          {websites?.map((site) => (
            <label key={site.id} className="member-website-option">
              <input
                type="checkbox"
                checked={value.includes(site.id)}
                onChange={(event) => onChange(event.target.checked ? [...value, site.id] : value.filter((id) => id !== site.id))}
              />
              {site.label}{site.archived_at ? " (Archived)" : ""}
            </label>
          ))}
        </div>
      )}
    </fieldset>
  );
}

function describeAccess(grant) {
  const role = workspaceRoleLabels[grant.role];
  if (grant.role !== "website_editor") return role;
  return `${role} · ${grant.website_ids == null ? "all websites" : `${grant.website_ids.length} selected`}`;
}

export default function AgencyAccess({ account, websites }) {
  const [grants, setGrants] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState("");
  const [preview, setPreview] = useState(null);
  const [draft, setDraft] = useState({ role: "manager", website_ids: null });
  const [editing, setEditing] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    listAgencyGrants(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setGrants(data);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    return () => controller.abort();
  }, [attempt]);

  async function run(action) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  function checkCode(event) {
    event.preventDefault();
    if (!code.trim()) return;
    run(async () => {
      setPreview(await previewAgency(code.trim()));
      setDraft({ role: "manager", website_ids: null });
    });
  }

  function grant(event) {
    event.preventDefault();
    run(async () => {
      const created = await grantAgencyAccess(code.trim(), draft.role, draft.role === "website_editor" ? draft.website_ids : null);
      setGrants((previous) => [...previous, created]);
      setPreview(null);
      setCode("");
    });
  }

  function saveChange(event) {
    event.preventDefault();
    run(async () => {
      const updated = await updateAgencyAccess(
        editing.agency_id, editing.role, editing.role === "website_editor" ? editing.website_ids : null,
      );
      setGrants((previous) => previous.map((item) => item.agency_id === updated.agency_id ? updated : item));
      setEditing(null);
    });
  }

  function revoke(item) {
    if (!window.confirm(`Revoke ${item.agency_name}'s access to ${account.business_name}? Agency staff lose access immediately. People you added directly under Team access keep their access.`)) return;
    run(async () => {
      await revokeAgencyAccess(item.agency_id);
      setGrants((previous) => previous.filter((grant) => grant.agency_id !== item.agency_id));
      if (editing?.agency_id === item.agency_id) setEditing(null);
    });
  }

  return (
    <section className="panel settings-panel workspace-settings">
      <h3>Agency access</h3>
      <p>
        You own {account.business_name}. An agency can work in this business only at the level you allow, and agency
        admins choose which of their staff work on it. Agencies never become owners. You can change or revoke their
        access at any time, and it takes effect immediately.
      </p>
      {grants?.length === 0 && <p>No agencies have access.</p>}
      {grants?.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Agency</th><th>Access</th><th>People with access</th><th>Actions</th></tr></thead>
            <tbody>
              {grants.map((item) => (
                <tr key={item.agency_id}>
                  <td>
                    <strong>{item.agency_name}</strong>
                    {item.created_client && <><br /><small className="muted">Set up this workspace for you</small></>}
                  </td>
                  <td>{describeAccess(item)}</td>
                  <td>
                    {item.people.length === 0 ? "No one" : item.people.map((person) => (
                      <div key={person.email}>
                        {person.email} · {workspaceRoleLabels[person.role]}{person.agency_role === "admin" ? " (agency admin)" : ""}
                      </div>
                    ))}
                  </td>
                  <td>
                    <button className="secondary" type="button" disabled={busy} onClick={() => {
                      setError("");
                      setEditing({ agency_id: item.agency_id, agency_name: item.agency_name, role: item.role, website_ids: item.website_ids ?? null });
                    }}>Change access</button>{" "}
                    <button className="secondary" type="button" disabled={busy} onClick={() => revoke(item)}>Revoke</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && (
        <form className="member-website-access" onSubmit={saveChange}>
          <fieldset className="website-catalog" disabled={busy}>
            <legend>Access for {editing.agency_name}</legend>
            <label className="website-picker">
              Highest role
              <select value={editing.role} onChange={(event) => setEditing((current) => ({ ...current, role: event.target.value }))}>
                {assignableWorkspaceRoles.map((role) => <option key={role} value={role}>{workspaceRoleLabels[role]}</option>)}
              </select>
            </label>
            {editing.role === "website_editor" && (
              <WebsiteScope websites={websites} value={editing.website_ids} disabled={busy}
                onChange={(ids) => setEditing((current) => ({ ...current, website_ids: ids }))} />
            )}
            <p className="muted">Lowering the role also lowers agency staff assigned above it.</p>
            <div className="member-website-actions">
              <button className="primary" type="submit">Save agency access</button>
              <button className="secondary" type="button" onClick={() => setEditing(null)}>Cancel</button>
            </div>
          </fieldset>
        </form>
      )}
      {grants && !preview && (
        <form className="workspace-form" onSubmit={checkCode}>
          <label>
            Agency access code
            <input required maxLength={40} value={code} disabled={busy} placeholder="ABCD-EFGH-JKLM"
              onChange={(event) => setCode(event.target.value)} />
          </label>
          <button className="primary" disabled={busy || !code.trim()}>Check code</button>
        </form>
      )}
      {preview && (
        <form className="member-website-access" onSubmit={grant}>
          <fieldset className="website-catalog" disabled={busy || preview.already_granted}>
            <legend>Grant access to {preview.name}</legend>
            {preview.already_granted ? <p>This agency already has access. Use Change access above.</p> : (
              <>
                <label className="website-picker">
                  Highest role
                  <select value={draft.role} onChange={(event) => setDraft((current) => ({ ...current, role: event.target.value }))}>
                    {assignableWorkspaceRoles.map((role) => <option key={role} value={role}>{workspaceRoleLabels[role]}</option>)}
                  </select>
                </label>
                {draft.role === "website_editor" && (
                  <WebsiteScope websites={websites} value={draft.website_ids} disabled={busy}
                    onChange={(ids) => setDraft((current) => ({ ...current, website_ids: ids }))} />
                )}
              </>
            )}
          </fieldset>
          <div className="member-website-actions">
            {!preview.already_granted && <button className="primary" type="submit" disabled={busy}>Grant access</button>}
            <button className="secondary" type="button" disabled={busy} onClick={() => setPreview(null)}>Cancel</button>
          </div>
        </form>
      )}
      {error && <p role="alert">{error}</p>}
      {!grants && !error && <p role="status">Loading agency access…</p>}
      {!grants && error && <button className="secondary" onClick={() => {
        setError("");
        setAttempt((previous) => previous + 1);
      }}>Retry</button>}
    </section>
  );
}
