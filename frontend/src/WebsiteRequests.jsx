import React, { useEffect, useState } from "react";
import { createWebsiteRequest, decideWebsiteRequest, listWebsiteRequests } from "./api";

const labels = { pending: "Pending", approved: "Approved", declined: "Declined" };

export default function WebsiteRequests({ platformAdmin = false, onRefreshWebsites }) {
  const [requests, setRequests] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [label, setLabel] = useState("");
  const [notes, setNotes] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    listWebsiteRequests(platformAdmin, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setRequests(data);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    return () => controller.abort();
  }, [platformAdmin, attempt]);

  function refresh() {
    setRequests(null);
    setError("");
    setAttempt((previous) => previous + 1);
    onRefreshWebsites?.();
  }

  async function sendRequest(event) {
    event.preventDefault();
    if (busy || !label.trim()) return;
    setBusy(true);
    setError("");
    try {
      const request = await createWebsiteRequest(label.trim(), notes.trim());
      setRequests((previous) => [request, ...previous]);
      setLabel("");
      setNotes("");
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  async function decide(request, status) {
    if (busy) return;
    const prompt = status === "approved"
      ? `Create a draft website named "${request.label}" for ${request.business_name}?`
      : `Decline the request for "${request.label}" from ${request.business_name}?`;
    if (!window.confirm(prompt)) return;
    setBusy(true);
    setError("");
    try {
      const updated = await decideWebsiteRequest(request.id, status);
      setRequests((previous) => previous.map((item) => item.id === updated.id ? updated : item));
      if (status === "approved") onRefreshWebsites?.();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel settings-panel website-requests">
      <div className="settings-panel-header">
        <h3>Website requests</h3>
        <button className="secondary" type="button" disabled={busy} onClick={refresh}>Refresh requests</button>
      </div>
      {!platformAdmin && requests && (
        <form className="workspace-form" onSubmit={sendRequest}>
          <label>
            Requested website name
            <input required maxLength={100} value={label} disabled={busy} onChange={(event) => setLabel(event.target.value)} />
          </label>
          <label>
            Notes for platform admin (optional)
            <input maxLength={300} value={notes} disabled={busy} onChange={(event) => setNotes(event.target.value)} />
          </label>
          <button className="primary" disabled={busy || !label.trim()}>Request website</button>
        </form>
      )}
      {error && <p role="alert">{error}</p>}
      {!requests && !error && <p role="status">Loading website requests…</p>}
      {requests?.length === 0 && <p>No website requests yet.</p>}
      {requests?.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {platformAdmin && <th scope="col">Business</th>}
                <th scope="col">Website</th>
                <th scope="col">Status</th>
                <th scope="col">Requested by</th>
                {platformAdmin && <th scope="col">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {requests.map((request) => (
                <tr key={request.id}>
                  {platformAdmin && <td>{request.business_name}</td>}
                  <td className="website-request-note">
                    <strong>{request.label}</strong>
                    {request.notes && <p>{request.notes}</p>}
                  </td>
                  <td>
                    {labels[request.status]}
                    {request.decided_at && <div className="muted">{new Date(request.decided_at).toLocaleDateString("en-IN")}</div>}
                  </td>
                  <td>{request.requested_by}</td>
                  {platformAdmin && (
                    <td>
                      {request.status === "pending" ? (
                        <>
                          <button className="secondary" disabled={busy} onClick={() => decide(request, "approved")}>Approve</button>{" "}
                          <button className="secondary" disabled={busy} onClick={() => decide(request, "declined")}>Decline</button>
                        </>
                      ) : request.decided_by}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
