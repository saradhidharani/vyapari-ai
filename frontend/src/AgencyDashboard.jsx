import React, { useEffect, useState } from "react";
import { BarChart3, Briefcase, Globe, RotateCcw } from "lucide-react";
import { getAgencyDashboard } from "./api";
import { Stat, money, periodLabel, salesPeriods } from "./reporting";
import { workspaceRoleLabels } from "./workspaceRoles";

const dateFormat = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });

function dateRange(report) {
  const start = dateFormat.format(new Date(`${report.start_date}T00:00:00Z`));
  const end = dateFormat.format(new Date(`${report.end_date}T00:00:00Z`));
  return start === end ? start : `${start} – ${end}`;
}

export default function AgencyDashboard({ agency, onOpenWorkspace, version }) {
  const [period, setPeriod] = useState("last 7 days");
  const [report, setReport] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [opening, setOpening] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    getAgencyDashboard(agency.id, period, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setReport(data);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(failure.message);
      });
    return () => controller.abort();
  }, [agency.id, period, attempt, version]);

  async function open(client) {
    if (opening) return;
    setOpening(client.business_id);
    setError("");
    try {
      // A successful switch remounts the app in the client's workspace.
      await onOpenWorkspace(client.business_id);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setOpening(null);
    }
  }

  const current = report?.period === period ? report : null;
  return (
    <section className="panel settings-panel workspace-settings agency-dashboard">
      <div className="settings-panel-header">
        <div>
          <h3>Client dashboard</h3>
          <p>
            Clients you can open through {agency.name}.
            {current && ` Sales from ${dateRange(current)}, India Standard Time.`}
          </p>
        </div>
        <div className="sales-actions">
        <label className="sales-period">
          Date range
          <select value={period} onChange={(event) => setPeriod(event.target.value)}>
            {salesPeriods.map((item) => <option key={item} value={item}>{periodLabel(item)}</option>)}
          </select>
        </label>
        <button className="secondary" type="button" onClick={() => setAttempt((previous) => previous + 1)}>Refresh</button>
        </div>
      </div>
      {current && (
        <>
          <div className="stats">
            <Stat label="Combined net sales" value={money(current.combined.net_paise / 100)}
              change={`${current.reported_clients} ${current.reported_clients === 1 ? "client" : "clients"} with report access`}
              icon={BarChart3} />
            <Stat label="Payments" value={money(current.combined.payments_paise / 100)}
              change={`${current.combined.payment_count} paid orders`} icon={Briefcase} />
            <Stat label="Refunds" value={money(current.combined.refunds_paise / 100)}
              change={`${current.combined.refund_count} refunded orders`} icon={RotateCcw} />
            <Stat label="Clients" value={current.clients.length}
              change={current.clients_without_report_access ? `${current.clients_without_report_access} without report access` : "All with report access"}
              icon={Globe} />
          </div>
          {current.clients.length === 0 ? (
            <p>{agency.role === "admin" ? "No clients have granted access yet." : "No clients are assigned to you."}</p>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr><th>Business</th><th>Your role</th><th>Websites</th><th>Payments</th><th>Refunds</th><th>Net sales</th><th>Actions</th></tr>
                </thead>
                <tbody>
                  {current.clients.map((client) => (
                    <tr key={client.business_id}>
                      <td><strong>{client.business_name}</strong></td>
                      <td>{workspaceRoleLabels[client.role]}</td>
                      <td title={client.website_count == null ? "No website access" : undefined}>{client.website_count ?? "—"}</td>
                      {client.report_access ? (
                        <>
                          <td>{money(client.sales.payments_paise / 100)}</td>
                          <td>{money(client.sales.refunds_paise / 100)}</td>
                          <td><strong>{money(client.sales.net_paise / 100)}</strong></td>
                        </>
                      ) : <td colSpan={3} className="muted">No report access</td>}
                      <td>
                        <button className="secondary" type="button" disabled={opening !== null} onClick={() => open(client)}>
                          {opening === client.business_id ? "Opening…" : "Open workspace"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <p className="muted">Combined totals include only clients where your role allows sales reports. Each client's records stay in its own workspace.</p>
        </>
      )}
      {!current && !error && <p role="status">Loading dashboard…</p>}
      {error && <p role="alert">{error}</p>}
      {error && !current && <button className="secondary" onClick={() => setAttempt((previous) => previous + 1)}>Retry</button>}
    </section>
  );
}
