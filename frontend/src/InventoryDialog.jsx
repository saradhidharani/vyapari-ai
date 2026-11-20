import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { adjustProductStock, getStockHistory } from "./api";

const timestamp = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" });

export default function InventoryDialog({ product, onUpdate, onClose }) {
  const dialog = useRef(null);
  const pending = useRef(null);
  const [history, setHistory] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [direction, setDirection] = useState("add");
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState("");

  useLayoutEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getStockHistory(product.id, controller.signal)
      .then((page) => { if (!controller.signal.aborted) setHistory(page); })
      .catch((failure) => { if (!controller.signal.aborted) setHistoryError(failure.message); });
    return () => controller.abort();
  }, [product.id, attempt]);

  function refresh() {
    setHistory(null);
    setHistoryError("");
    setAttempt((previous) => previous + 1);
  }

  async function loadOlder() {
    if (historyBusy || history?.older_before == null) return;
    setHistoryBusy(true);
    setHistoryError("");
    try {
      const page = await getStockHistory(product.id, undefined, history.older_before);
      setHistory((previous) => ({
        movements: [...previous.movements, ...page.movements],
        older_before: page.older_before,
      }));
    } catch (failure) {
      setHistoryError(failure.message);
    } finally {
      setHistoryBusy(false);
    }
  }

  async function submit(event) {
    event.preventDefault();
    if (busy || historyBusy) return;
    const units = Number(quantity);
    if (!Number.isSafeInteger(units) || units <= 0 || !reason.trim()) {
      setError("Enter a positive whole number and a reason.");
      return;
    }
    const delta = direction === "add" ? units : -units;
    const note = reason.trim();
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      if (pending.current?.delta !== delta || pending.current?.reason !== note) {
        pending.current = { delta, reason: note, request_id: crypto.randomUUID() };
      }
      onUpdate(await adjustProductStock(product.id, pending.current));
      pending.current = null;
      setQuantity("");
      setReason("");
      setSaved(true);
      refresh();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog className="modal order-details" ref={dialog} aria-labelledby="inventory-title"
      onCancel={(event) => { if (busy) event.preventDefault(); }}
      onClose={(event) => { if (!event.currentTarget.open) onClose(); }}>
      <div className="modal-title">
        <h3 id="inventory-title">Stock for {product.name}</h3>
        <button type="button" disabled={busy} aria-label="Close inventory" onClick={() => dialog.current.close()}>
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      <p><strong>{product.stock} in stock</strong> · Low-stock threshold {product.low_stock_threshold}
        {" · "}Target stock {product.restock_target ?? product.low_stock_threshold}</p>
      <form className="workspace-form inventory-adjustment" onSubmit={submit}>
        <label>
          Adjustment
          <select disabled={busy} value={direction} onChange={(event) => setDirection(event.target.value)}>
            <option value="add">Add units</option><option value="remove">Remove units</option>
          </select>
        </label>
        <label>
          Units
          <input type="number" min={1} required disabled={busy} value={quantity} onChange={(event) => setQuantity(event.target.value)} />
        </label>
        <label>
          Reason
          <input required maxLength={200} disabled={busy} value={reason} placeholder="e.g. Delivery received"
            onChange={(event) => setReason(event.target.value)} />
        </label>
        <button className="primary" disabled={busy || historyBusy}>{busy ? "Saving…" : "Save adjustment"}</button>
      </form>
      {saved && <p role="status">Stock adjustment saved.</p>}
      {error && <p role="alert">{error}</p>}
      <div className="settings-panel-header">
        <h4>Movement history</h4>
        <button className="secondary" type="button" disabled={busy || historyBusy} onClick={refresh}>Refresh history</button>
      </div>
      {historyError && <p role="alert">{historyError}</p>}
      {!history && !historyError && <p role="status">Loading stock history…</p>}
      {history?.movements.length === 0 && <p>No stock movements recorded yet.</p>}
      {history?.movements.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Date (IST)</th><th>Change</th><th>Balance</th><th>Details</th><th>By</th></tr></thead>
            <tbody>
              {history.movements.map((item) => (
                <tr key={item.id}>
                  <td><time dateTime={item.created_at}>{timestamp.format(new Date(item.created_at))}</time></td>
                  <td>{item.delta > 0 ? `+${item.delta}` : item.delta}</td>
                  <td>{item.stock_after}</td>
                  <td>{item.action}{item.order_id && ` · #ORD-${item.order_id}`}{item.reason && ` · ${item.reason}`}</td>
                  <td>{item.actor}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {history?.older_before != null && (
        <button className="secondary" type="button" disabled={busy || historyBusy} onClick={loadOlder}>
          {historyBusy ? "Loading…" : "Load older movements"}
        </button>
      )}
    </dialog>
  );
}
