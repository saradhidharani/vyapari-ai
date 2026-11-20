import React, { useEffect, useState } from "react";
import {
  addAgencyMember,
  assignAgencyStaff,
  createAgency,
  createAgencyClient,
  listAgencies,
  listAgencyClients,
  listAgencyMembers,
  reissueOwnerInvitation,
  removeAgencyMember,
  unassignAgencyStaff,
  updateAgencyMember,
  withdrawFromClient,
} from "./api";
import { assignableWorkspaceRoles, workspaceRoleLabels } from "./workspaceRoles";
import AgencyDashboard from "./AgencyDashboard";

const agencyRoleLabels = { admin: "Agency admin", staff: "Agency staff" };

function ownerLabel(client) {
  if (client.owner_status === "owner") return "Client owner";
  if (client.owner_status === "invitation_pending") {
    return client.pending_owner_email ? `Invitation pending (${client.pending_owner_email})` : "Invitation pending";
  }
  return "No owner yet";
}

function invitationUrl(token) {
  return `${window.location.origin}/#invite=${token}`;
}

function AgencyDetail({ agency, onOpenWorkspace, onWorkspacesChanged }) {
  const admin = agency.role === "admin";
  const [clients, setClients] = useState(null);
  const [members, setMembers] = useState(admin ? null : []);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [staffFor, setStaffFor] = useState(null);
  const [assignment, setAssignment] = useState({ user_id: "", role: "" });
  const [memberDraft, setMemberDraft] = useState({ email: "", role: "staff" });
  const [clientDraft, setClientDraft] = useState({ business_name: "", owner_email: "" });
  const [link, setLink] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      listAgencyClients(agency.id, controller.signal),
      admin ? listAgencyMembers(agency.id, controller.signal) : Promise.resolve([]),
    ])
      .then(([clientList, memberList]) => {
        if (controller.signal.aborted) return;
        setClients(clientList);
        setMembers(memberList);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    return () => controller.abort();
  }, [agency.id, admin, attempt]);

  async function run(action, success = "") {
    if (busy) return;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      await action();
      if (success) setStatus(success);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  const refresh = () => setAttempt((previous) => previous + 1);
  const staffMembers = (members ?? []).filter((member) => member.role === "staff");
  const rolesFor = (client) => client.grant_role === "manager" ? assignableWorkspaceRoles : [client.grant_role];

  function openStaff(client) {
    setStaffFor(client.business_id);
    setAssignment({ user_id: "", role: rolesFor(client)[0] });
  }

  function assign(event, client) {
    event.preventDefault();
    if (!assignment.user_id) return;
    run(async () => {
      await assignAgencyStaff(agency.id, client.business_id, assignment.user_id, assignment.role);
      setAssignment({ user_id: "", role: rolesFor(client)[0] });
      refresh();
    }, "Staff assignment saved.");
  }

  function addClient(event) {
    event.preventDefault();
    run(async () => {
      const created = await createAgencyClient(agency.id, clientDraft.business_name.trim(), clientDraft.owner_email.trim());
      setLink({ business: created.business_name, email: created.invitation.email, url: invitationUrl(created.invitation.token) });
      setClientDraft({ business_name: "", owner_email: "" });
      refresh();
      onWorkspacesChanged();
    });
  }

  function newOwnerLink(client) {
    const email = window.prompt(`Owner email for ${client.business_name}`, client.pending_owner_email ?? "");
    if (!email?.trim()) return;
    run(async () => {
      const invitation = await reissueOwnerInvitation(agency.id, client.business_id, email.trim());
      setLink({ business: client.business_name, email: invitation.email, url: invitationUrl(invitation.token) });
      refresh();
    });
  }

  function withdraw(client) {
    if (!window.confirm(`Remove ${agency.name}'s access to ${client.business_name}? The client owner keeps the workspace.`)) return;
    run(async () => {
      await withdrawFromClient(agency.id, client.business_id);
      refresh();
      onWorkspacesChanged();
    });
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(link.url);
      setStatus("Owner invitation link copied.");
    } catch {
      setStatus("Select the link and copy it.");
    }
  }

  return (
    <>
      <AgencyDashboard agency={agency} onOpenWorkspace={onOpenWorkspace} version={attempt} />
      <section className="panel settings-panel workspace-settings">
        <h3>{agency.name}</h3>
        <p>You are an {agencyRoleLabels[agency.role].toLowerCase()}. {admin
          ? "Admins work in every client at the level the client granted and choose which staff work on each client."
          : "You can open the clients an agency admin assigned to you."}</p>
        {admin && (
          <div className="setting-row">
            <span>Agency access code</span>
            <strong>{agency.access_code}</strong>
            <small className="muted">A business owner enters this code in Settings → Agency access to grant your agency access.</small>
          </div>
        )}
      </section>

      <section className="panel settings-panel workspace-settings">
        <h3>Client businesses</h3>
        <p>Each client's products, customers, orders, and websites stay in its own workspace. Clients choose your
          agency's highest role and can revoke access at any time.</p>
        {clients?.length === 0 && <p>{admin ? "No clients have granted access yet." : "No clients are assigned to you."}</p>}
        {clients?.length > 0 && (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Business</th><th>Granted access</th><th>Ownership</th><th>Your role</th><th>Actions</th></tr></thead>
              <tbody>
                {clients.map((client) => (
                  <React.Fragment key={client.business_id}>
                    <tr>
                      <td><strong>{client.business_name}</strong>{client.created_by_agency && <><br /><small className="muted">Set up by your agency</small></>}</td>
                      <td>{workspaceRoleLabels[client.grant_role]}{client.grant_role === "website_editor" && (client.website_ids == null ? " · all websites" : ` · ${client.website_ids.length} websites`)}</td>
                      <td>{ownerLabel(client)}</td>
                      <td>{workspaceRoleLabels[client.your_role]}</td>
                      <td>
                        <button className="secondary" type="button" disabled={busy}
                          onClick={() => run(() => onOpenWorkspace(client.business_id))}>Open workspace</button>{" "}
                        {admin && <button className="secondary" type="button" disabled={busy}
                          onClick={() => staffFor === client.business_id ? setStaffFor(null) : openStaff(client)}>Staff</button>}{" "}
                        {admin && client.created_by_agency && client.owner_status !== "owner" && (
                          <button className="secondary" type="button" disabled={busy} onClick={() => newOwnerLink(client)}>New owner link</button>
                        )}{" "}
                        {admin && client.owner_status === "owner" && (
                          <button className="secondary" type="button" disabled={busy} onClick={() => withdraw(client)}>Withdraw</button>
                        )}
                      </td>
                    </tr>
                    {admin && staffFor === client.business_id && (
                      <tr>
                        <td colSpan={5}>
                          {client.assignments.length === 0 ? <p>No staff assigned. Agency admins already have access.</p> : client.assignments.map((item) => (
                            <div key={item.user_id} className="setting-row">
                              <span>{item.email}</span>
                              <strong>{workspaceRoleLabels[item.role]}</strong>
                              <button className="secondary" type="button" disabled={busy} onClick={() => run(async () => {
                                await unassignAgencyStaff(agency.id, client.business_id, item.user_id);
                                refresh();
                              })}>Unassign</button>
                            </div>
                          ))}
                          {staffMembers.length === 0 ? <p className="muted">Add agency staff below to assign them.</p> : (
                            <form className="workspace-form" onSubmit={(event) => assign(event, client)}>
                              <label>
                                Staff member
                                <select value={assignment.user_id} disabled={busy}
                                  onChange={(event) => setAssignment((current) => ({ ...current, user_id: Number(event.target.value) || "" }))}>
                                  <option value="">Choose staff</option>
                                  {staffMembers.map((member) => <option key={member.id} value={member.id}>{member.email}</option>)}
                                </select>
                              </label>
                              <label>
                                Role
                                <select value={assignment.role} disabled={busy}
                                  onChange={(event) => setAssignment((current) => ({ ...current, role: event.target.value }))}>
                                  {rolesFor(client).map((role) => <option key={role} value={role}>{workspaceRoleLabels[role]}</option>)}
                                </select>
                              </label>
                              <button className="primary" disabled={busy || !assignment.user_id}>Assign</button>
                            </form>
                          )}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {link && (
          <div className="workspace-form">
            <label>
              Owner invitation for {link.business} ({link.email})
              <input readOnly value={link.url} onFocus={(event) => event.target.select()} />
            </label>
            <button className="secondary" type="button" onClick={copyLink}>Copy link</button>
          </div>
        )}
        {admin && (
          <>
            <h3>Set up a new client</h3>
            <p>Create a workspace and an owner invitation for the client. Until they accept, the workspace has no owner
              and your agency manages it. Once they accept, the client owns the workspace and controls your access.
              Invitation links expire after seven days.</p>
            <form className="workspace-form" onSubmit={addClient}>
              <label>
                Business name
                <input required maxLength={100} disabled={busy} value={clientDraft.business_name}
                  onChange={(event) => setClientDraft((current) => ({ ...current, business_name: event.target.value }))} />
              </label>
              <label>
                Client owner email
                <input type="email" required maxLength={254} disabled={busy} value={clientDraft.owner_email}
                  onChange={(event) => setClientDraft((current) => ({ ...current, owner_email: event.target.value }))} />
              </label>
              <button className="primary" disabled={busy || !clientDraft.business_name.trim() || !clientDraft.owner_email.trim()}>Create client workspace</button>
            </form>
          </>
        )}
      </section>

      {admin && members && (
        <section className="panel settings-panel workspace-settings">
          <h3>Agency team</h3>
          <p>Admins manage the agency and work in every client. Staff only see clients assigned to them.</p>
          <div className="table-scroll">
            <table>
              <thead><tr><th>Email</th><th>Role</th><th>Actions</th></tr></thead>
              <tbody>
                {members.map((member) => (
                  <tr key={member.id}>
                    <td>{member.email}</td>
                    <td>
                      <select aria-label={`Agency role for ${member.email}`} value={member.role} disabled={busy}
                        onChange={(event) => run(async () => {
                          const updated = await updateAgencyMember(agency.id, member.id, event.target.value);
                          setMembers((previous) => previous.map((item) => item.id === updated.id ? updated : item));
                          refresh();
                        })}>
                        {Object.entries(agencyRoleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                    </td>
                    <td>
                      <button className="secondary" type="button" disabled={busy} onClick={() => {
                        if (!window.confirm(`Remove ${member.email} from ${agency.name}? They lose access to every client through this agency.`)) return;
                        run(async () => {
                          await removeAgencyMember(agency.id, member.id);
                          refresh();
                        });
                      }}>Remove</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <form className="workspace-form" onSubmit={(event) => {
            event.preventDefault();
            run(async () => {
              const added = await addAgencyMember(agency.id, memberDraft.email.trim(), memberDraft.role);
              setMembers((previous) => [...previous, added]);
              setMemberDraft({ email: "", role: "staff" });
            });
          }}>
            <label>
              Existing Vyapari account email
              <input type="email" required maxLength={254} disabled={busy} value={memberDraft.email}
                onChange={(event) => setMemberDraft((current) => ({ ...current, email: event.target.value }))} />
            </label>
            <label>
              Role
              <select value={memberDraft.role} disabled={busy}
                onChange={(event) => setMemberDraft((current) => ({ ...current, role: event.target.value }))}>
                {Object.entries(agencyRoleLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <button className="primary" disabled={busy || !memberDraft.email.trim()}>Add to agency</button>
          </form>
        </section>
      )}
      {status && <p role="status">{status}</p>}
      {error && <p role="alert">{error}</p>}
      {!clients && !error && <p role="status">Loading clients…</p>}
      {!clients && error && <button className="secondary" onClick={() => {
        setError("");
        refresh();
      }}>Retry</button>}
    </>
  );
}

export default function Agencies({ onOpenWorkspace, onWorkspacesChanged }) {
  const [agencies, setAgencies] = useState(null);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    listAgencies(controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return;
        setAgencies(data);
        setSelected((current) => data.some((item) => item.id === current) ? current : data[0]?.id ?? null);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    return () => controller.abort();
  }, [attempt]);

  async function addAgency(event) {
    event.preventDefault();
    if (busy || !name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const created = await createAgency(name.trim());
      setAgencies((previous) => [...previous, created]);
      setSelected(created.id);
      setName("");
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  const agency = agencies?.find((item) => item.id === selected);
  return (
    <>
      {agencies?.length > 1 && (
        <section className="panel settings-panel workspace-settings">
          <label className="website-picker">
            Agency
            <select value={selected ?? ""} onChange={(event) => setSelected(Number(event.target.value))}>
              {agencies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
        </section>
      )}
      {agency && <AgencyDetail key={agency.id} agency={agency} onOpenWorkspace={onOpenWorkspace} onWorkspacesChanged={onWorkspacesChanged} />}
      <section className="panel settings-panel workspace-settings">
        <h3>{agencies?.length ? "Create another agency" : "Create an agency"}</h3>
        <p>An agency manages separate client businesses from one login. Each client decides what your agency can access.</p>
        <form className="workspace-form" onSubmit={addAgency}>
          <label>
            Agency name
            <input required maxLength={100} disabled={busy} value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <button className="primary" disabled={busy || !name.trim()}>Create agency</button>
        </form>
        {error && <p role="alert">{error}</p>}
        {!agencies && error && <button className="secondary" onClick={() => {
          setError("");
          setAttempt((previous) => previous + 1);
        }}>Retry</button>}
      </section>
    </>
  );
}
