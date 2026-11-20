import React, { useEffect, useState } from "react";
import {
  createWebsiteInquiryCustomer,
  linkWebsiteInquiryCustomer,
  listWebsiteInquiries,
  saveWebsiteInquiryNotes,
  updateWebsiteInquiry,
} from "./api";

const statuses = { new: "New", in_progress: "In progress", resolved: "Resolved" };
const timestamp = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" });

export default function WebsiteInquiries({
  customers, orders, canCreateOrders, onCustomerCreated, onNewOrder, onOpenOrder,
}) {
  const [inquiries, setInquiries] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [website, setWebsite] = useState("");
  const [draft, setDraft] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    listWebsiteInquiries(controller.signal)
      .then((items) => { if (!controller.signal.aborted) setInquiries(items); })
      .catch((error) => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [attempt]);

  function refresh() {
    setInquiries(null);
    setError("");
    setAttempt((previous) => previous + 1);
  }

  async function changeStatus(inquiry, nextStatus) {
    if (busy || inquiry.status === nextStatus) return;
    setBusy(true);
    setError("");
    try {
      const updated = await updateWebsiteInquiry(inquiry.id, nextStatus);
      setInquiries((previous) => previous.map((item) => item.id === updated.id ? updated : item));
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  function openDetails(item) {
    setDraft({
      id: item.id, customerId: item.customer_id == null ? "" : String(item.customer_id), notes: item.notes,
    });
  }

  async function saveFollowUp(item, action) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      let updated;
      if (action === "create") {
        const result = await createWebsiteInquiryCustomer(item.id);
        onCustomerCreated(result.customer);
        updated = result.inquiry;
      } else if (action === "link") {
        updated = await linkWebsiteInquiryCustomer(item.id, draft.customerId ? Number(draft.customerId) : null);
      } else {
        updated = await saveWebsiteInquiryNotes(item.id, draft.notes);
      }
      setInquiries((previous) => previous.map((entry) => entry.id === updated.id ? updated : entry));
      setDraft((previous) => ({
        ...previous,
        ...(action === "notes"
          ? { notes: updated.notes }
          : { customerId: updated.customer_id == null ? "" : String(updated.customer_id) }),
      }));
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  const websites = new Map((inquiries ?? []).map((item) => [item.website_id, item.website_label]));
  const ordersByInquiry = new Map(orders.filter((order) => order.source_inquiry_id).map((order) => [order.source_inquiry_id, order.id]));
  const visible = inquiries?.filter((item) =>
    (!status || item.status === status) && (!website || String(item.website_id) === website)
  );

  return (
    <section className="panel settings-panel">
      <div className="settings-panel-header enquiry-filters">
        <label className="sales-period">
          Website
          <select value={website} onChange={(event) => setWebsite(event.target.value)}>
            <option value="">All websites</option>
            {[...websites].map(([id, label]) => <option key={id} value={id}>{label}</option>)}
          </select>
        </label>
        <label className="sales-period">
          Status
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="">All statuses</option>
            {Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <button className="secondary" type="button" disabled={busy} onClick={refresh}>Refresh enquiries</button>
      </div>
      {error && <p role="alert">{error}</p>}
      {!inquiries && !error && <p role="status">Loading enquiries…</p>}
      {inquiries?.length === 0 && <p>No website enquiries yet.</p>}
      {inquiries?.length > 0 && visible?.length === 0 && <p>No enquiries match your filters.</p>}
      {visible?.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>From</th><th>Website</th><th>Message</th><th>Received (IST)</th><th>Status</th><th>Follow-up</th></tr>
            </thead>
            <tbody>
              {visible.map((item) => {
                const orderId = ordersByInquiry.get(item.id) ?? item.order_id;
                return <React.Fragment key={item.id}>
                <tr>
                  <td className="enquiry-message">
                    <strong>{item.name}</strong>
                    {item.email && <div>{item.email}</div>}
                    {item.phone && <div>{item.phone}</div>}
                  </td>
                  <td>{item.website_label}</td>
                  <td className="enquiry-message">{item.message}</td>
                  <td><time dateTime={item.created_at}>{timestamp.format(new Date(item.created_at))}</time></td>
                  <td>
                    <select
                      aria-label={`Status for enquiry ${item.id}`}
                      value={item.status}
                      disabled={busy}
                      onChange={(event) => changeStatus(item, event.target.value)}
                    >
                      {Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                    </select>
                  </td>
                  <td>
                    <button className="secondary" type="button" disabled={busy} onClick={() => {
                      if (draft?.id === item.id) setDraft(null);
                      else openDetails(item);
                    }} aria-expanded={draft?.id === item.id}>
                      {draft?.id === item.id ? "Close details" : "Open details"}
                    </button>
                  </td>
                </tr>
                {draft?.id === item.id && (
                  <tr>
                    <td colSpan={6}>
                      <div className="enquiry-follow-up">
                        <h4>Customer and order</h4>
                        {item.customer_name && <p>Linked customer • {item.customer_name}</p>}
                        <form className="workspace-form" onSubmit={(event) => {
                          event.preventDefault();
                          saveFollowUp(item, "link");
                        }}>
                          <label>
                            Customer
                            <select
                              value={draft.customerId}
                              disabled={busy || !customers}
                              onChange={(event) => setDraft({ ...draft, customerId: event.target.value })}
                            >
                              <option value="">No linked customer</option>
                              {customers?.map((customer) => (
                                <option key={customer.id} value={customer.id}>
                                  {customer.name}{customer.email ? ` · ${customer.email}` : customer.phone ? ` · ${customer.phone}` : ""}
                                </option>
                              ))}
                            </select>
                          </label>
                          <button className="secondary" type="submit" disabled={busy || !customers}>
                            Save customer link
                          </button>
                          {item.customer_id == null && (
                            <button className="secondary" type="button" disabled={busy || !customers} onClick={() => saveFollowUp(item, "create")}>
                              Create customer from enquiry
                            </button>
                          )}
                        </form>
                        {orderId ? (
                          <button className="secondary" type="button" disabled={!orders.some((order) => order.id === orderId)}
                            onClick={() => onOpenOrder(orderId)}>View order #ORD-{orderId}</button>
                        ) : (
                          <button className="primary" type="button"
                            disabled={busy || !canCreateOrders || !customers?.some((customer) => customer.id === item.customer_id)}
                            onClick={() => onNewOrder(item)}>Create order from enquiry</button>
                        )}
                        <form className="workspace-form enquiry-notes" onSubmit={(event) => {
                          event.preventDefault();
                          saveFollowUp(item, "notes");
                        }}>
                          <label>
                            Internal notes
                            <textarea rows={3} maxLength={2000} value={draft.notes} disabled={busy}
                              onChange={(event) => setDraft({ ...draft, notes: event.target.value })} />
                          </label>
                          <button className="secondary" type="submit" disabled={busy || draft.notes.trim() === item.notes}>
                            Save notes
                          </button>
                        </form>
                        {item.notes_updated_at && (
                          <p>Last updated by {item.notes_updated_by} · {timestamp.format(new Date(item.notes_updated_at))} IST</p>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
                </React.Fragment>;
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
