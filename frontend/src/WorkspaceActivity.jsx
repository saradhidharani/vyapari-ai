import React, { useEffect, useState } from "react";
import { listWorkspaceActivity } from "./api";

const timestamp = new Intl.DateTimeFormat("en-IN", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Kolkata",
});

export default function WorkspaceActivity() {
  const [activity, setActivity] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [loadingOlder, setLoadingOlder] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    listWorkspaceActivity(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setActivity(data);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    return () => controller.abort();
  }, [attempt]);

  function refresh() {
    setActivity(null);
    setError("");
    setAttempt((previous) => previous + 1);
  }

  async function loadOlder() {
    if (loadingOlder || activity?.older_before == null) return;
    setLoadingOlder(true);
    setError("");
    try {
      const page = await listWorkspaceActivity(undefined, activity.older_before);
      setActivity((previous) => ({
        events: [...previous.events, ...page.events],
        older_before: page.older_before,
      }));
    } catch (failure) {
      setError(failure.message);
    } finally {
      setLoadingOlder(false);
    }
  }

  return (
    <section className="panel settings-panel workspace-settings">
      <div className="settings-panel-header">
        <h3>Activity log</h3>
        <button className="secondary" type="button" disabled={loadingOlder} onClick={refresh}>Refresh activity</button>
      </div>
      {error && <p role="alert">{error}</p>}
      {!activity && !error && <p role="status">Loading activity…</p>}
      {activity?.events.length === 0 && <p>No activity recorded yet.</p>}
      {activity?.events.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead><tr><th scope="col">Date (IST)</th><th scope="col">Action</th><th scope="col">Details</th><th scope="col">By</th></tr></thead>
            <tbody>
              {activity.events.map((event) => (
                <tr key={event.id}>
                  <td><time dateTime={event.created_at}>{timestamp.format(new Date(event.created_at))}</time></td>
                  <td>{event.action}</td>
                  <td>{event.details}</td>
                  <td>{event.actor}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {activity?.older_before != null && (
        <button className="secondary" type="button" disabled={loadingOlder} onClick={loadOlder}>
          {loadingOlder ? "Loading…" : "Load older activity"}
        </button>
      )}
    </section>
  );
}
