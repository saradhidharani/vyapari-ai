import React, { useEffect, useState } from "react";
import { listPlatformBusinesses } from "./api";

export default function PlatformBusinesses() {
  const [businesses, setBusinesses] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    listPlatformBusinesses(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setBusinesses(data);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    return () => controller.abort();
  }, [attempt]);

  return (
    <div className="panel table-scroll">
      {error ? (
        <div className="empty">
          <p role="alert">{error}</p>
          <button className="secondary" onClick={() => {
            setError("");
            setAttempt((previous) => previous + 1);
          }}>Retry</button>
        </div>
      ) : !businesses ? (
        <p className="empty" role="status">Loading businesses…</p>
      ) : !businesses.length ? (
        <p className="empty">No businesses yet.</p>
      ) : (
        <table>
          <thead><tr><th>Business</th><th>Owner</th><th>Members</th><th>Websites</th></tr></thead>
          <tbody>
            {businesses.map((business) => (
              <tr key={business.id}>
                <td><strong>{business.name}</strong> <span className="muted">#{business.id}</span></td>
                <td>{business.owner_emails.join(", ") || "—"}</td>
                <td>{business.member_count}</td>
                <td>
                  {business.published_website_count} published / {business.website_count} total
                  {business.archived_website_count > 0 && ` · ${business.archived_website_count} archived`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
