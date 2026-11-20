import React, { useEffect, useState } from "react";
import {
  createWorkspace,
  grantWorkspaceMember,
  listWorkspaceMembers,
  revokeWorkspaceMember,
  updateMemberWebsiteAccess,
  updateWorkspaceMember,
} from "./api";
import { assignableWorkspaceRoles, workspaceRoleLabels } from "./workspaceRoles";

export default function WorkspaceSettings({ account, websites, onWorkspaceCreated }) {
  const [members, setMembers] = useState(null);
  const [teamError, setTeamError] = useState("");
  const [teamAttempt, setTeamAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("sales");
  const [websiteAccess, setWebsiteAccess] = useState(null);
  const [creation, setCreation] = useState({ busy: false, message: "", error: false });
  const owner = account.role === "owner";

  useEffect(() => {
    if (!owner) return;
    const controller = new AbortController();
    listWorkspaceMembers(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setMembers(data);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setTeamError(error.message);
      });
    return () => controller.abort();
  }, [owner, teamAttempt]);

  async function addBusiness(event) {
    event.preventDefault();
    if (!name.trim() || creation.busy) return;
    setCreation({ busy: true, message: "", error: false });
    try {
      await createWorkspace(name.trim());
      onWorkspaceCreated();
      setName("");
      setCreation({ busy: false, message: "Business created. Select it from the workspace menu.", error: false });
    } catch (error) {
      setCreation({ busy: false, message: error.message, error: true });
    }
  }

  async function grantMember(event) {
    event.preventDefault();
    if (!email.trim() || busy) return;
    setBusy(true);
    setTeamError("");
    try {
      const member = await grantWorkspaceMember(email.trim(), role);
      setMembers((previous) => [...previous, member]);
      setEmail("");
    } catch (error) {
      setTeamError(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function changeRole(member, nextRole) {
    if (busy || nextRole === member.role) return;
    setBusy(true);
    setTeamError("");
    try {
      const updated = await updateWorkspaceMember(member.id, nextRole);
      setMembers((previous) => previous.map((item) => item.id === updated.id ? updated : item));
      if (websiteAccess?.id === member.id && updated.role !== "website_editor") setWebsiteAccess(null);
    } catch (error) {
      setTeamError(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function removeMember(member) {
    if (busy || !window.confirm(`Remove ${member.email}'s access to ${account.business_name}?`)) return;
    setBusy(true);
    setTeamError("");
    try {
      await revokeWorkspaceMember(member.id);
      setMembers((previous) => previous.filter((item) => item.id !== member.id));
      if (websiteAccess?.id === member.id) setWebsiteAccess(null);
    } catch (error) {
      setTeamError(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function saveWebsiteAccess(event) {
    event.preventDefault();
    if (busy || !websiteAccess) return;
    setBusy(true);
    setTeamError("");
    try {
      const updated = await updateMemberWebsiteAccess(websiteAccess.id, websiteAccess.website_ids);
      setMembers((previous) => previous.map((member) => member.id === updated.id ? updated : member));
      setWebsiteAccess(null);
    } catch (error) {
      setTeamError(error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <section className="panel settings-panel workspace-settings">
        <h3>Create another business</h3>
        <p>Use your current login to manage a separate business.</p>
        <form className="workspace-form" onSubmit={addBusiness}>
          <label>
            Business name
            <input required maxLength={100} value={name} disabled={creation.busy} onChange={(event) => setName(event.target.value)} />
          </label>
          <button className="primary" disabled={creation.busy || !name.trim()}>Create business</button>
        </form>
        {creation.message && <p role={creation.error ? "alert" : "status"}>{creation.message}</p>}
      </section>
      {owner && (
        <section className="panel settings-panel workspace-settings">
          <h3>Team access</h3>
          <p>Sales staff handle customers and orders. Website editors update website drafts. Managers can also manage inventory, refunds, reports, and publishing. Owners control team access.</p>
          {members ? (
            <>
              <div className="table-scroll">
                <table>
                  <thead><tr><th>Email</th><th>Role</th><th>Actions</th></tr></thead>
                  <tbody>
                    {members.map((member) => (
                      <tr key={member.id}>
                        <td>{member.email}</td>
                        <td>{member.role === "owner" ? "Owner" : (
                          <select
                            aria-label={`Role for ${member.email}`}
                            value={member.role}
                            disabled={busy}
                            onChange={(event) => changeRole(member, event.target.value)}
                          >
                            {assignableWorkspaceRoles.map((role) => <option key={role} value={role}>{workspaceRoleLabels[role]}</option>)}
                          </select>
                        )}</td>
                        <td>
                          {member.role === "website_editor" && (
                            <>
                              <button className="secondary" type="button" disabled={busy} onClick={() => {
                                setTeamError("");
                                setWebsiteAccess({ ...member, website_ids: member.website_ids ?? null });
                              }}>Website access</button>{" "}
                              <span className="muted">
                                {member.website_ids == null ? "All websites" : member.website_ids.length ? `${member.website_ids.length} assigned` : "No websites"}
                              </span>{" "}
                            </>
                          )}
                          {member.role !== "owner" && (
                            <button className="secondary" type="button" disabled={busy} onClick={() => removeMember(member)}>
                              Remove access
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {websiteAccess && (
                <form className="member-website-access" onSubmit={saveWebsiteAccess}>
                  <fieldset className="website-catalog" disabled={busy}>
                    <legend>Website access for {websiteAccess.email}</legend>
                    <label className="website-picker">
                      Sites this person can edit
                      <select
                        value={websiteAccess.website_ids === null ? "all" : "assigned"}
                        onChange={(event) => {
                          const mode = event.target.value;
                          setWebsiteAccess((draft) => ({ ...draft, website_ids: mode === "all" ? null : [] }));
                        }}
                      >
                        <option value="assigned">Assigned websites only</option>
                        <option value="all">All current and future websites</option>
                      </select>
                    </label>
                    {websiteAccess.website_ids !== null && (
                      <>
                        {!websites && <p role="status">Website list unavailable. Reload the page to try again.</p>}
                        {websites?.length === 0 && <p>This business has no websites to assign.</p>}
                        <div className="website-product-list">
                          {websites?.map((site) => (
                            <label key={site.id} className="member-website-option">
                              <input
                                type="checkbox"
                                checked={websiteAccess.website_ids.includes(site.id)}
                                onChange={(event) => {
                                  const checked = event.target.checked;
                                  setWebsiteAccess((draft) => ({
                                    ...draft,
                                    website_ids: checked
                                      ? [...draft.website_ids, site.id]
                                      : draft.website_ids.filter((id) => id !== site.id),
                                  }));
                                }}
                              />
                              {site.label}{site.archived_at ? " (Archived)" : ""}
                            </label>
                          ))}
                        </div>
                      </>
                    )}
                    <div className="member-website-actions">
                      <button className="primary" type="submit">Save website access</button>
                      <button className="secondary" type="button" onClick={() => setWebsiteAccess(null)}>Cancel</button>
                    </div>
                  </fieldset>
                </form>
              )}
              <form className="workspace-form" onSubmit={grantMember}>
                <label>
                  Existing Vyapari account email
                  <input type="email" required maxLength={254} disabled={busy} value={email} onChange={(event) => setEmail(event.target.value)} />
                </label>
                <label>
                  Role
                  <select value={role} disabled={busy} onChange={(event) => setRole(event.target.value)}>
                    {assignableWorkspaceRoles.map((role) => <option key={role} value={role}>{workspaceRoleLabels[role]}</option>)}
                  </select>
                </label>
                <button className="primary" disabled={busy || !email.trim()}>Add member</button>
              </form>
            </>
          ) : !teamError && <p role="status">Loading team members…</p>}
          {teamError && <p role="alert">{teamError}</p>}
          {teamError && !members && (
            <button className="secondary" onClick={() => {
              setTeamError("");
              setTeamAttempt((attempt) => attempt + 1);
            }}>Retry</button>
          )}
        </section>
      )}
    </>
  );
}
