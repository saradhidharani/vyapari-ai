import React, { useEffect, useRef, useState } from "react";
import { apiRequest } from "./api";

const base = "/api/purchasing";
const emptySupplier = { name: "", email: "", phone: "" };
const emptyItem = { product_id: "", quantity: "1" };
const statuses = { ordered: "Ordered", received: "Received", cancelled: "Cancelled" };

export default function Purchasing({ products, productsReady, onReceived }) {
  const [data, setData] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [supplier, setSupplier] = useState(emptySupplier);
  const [supplierId, setSupplierId] = useState("");
  const [items, setItems] = useState([emptyItem]);
  const pending = useRef(null);

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal, cache: "no-store" };
    Promise.all([apiRequest(`${base}/suppliers`, options), apiRequest(`${base}/orders`, options)])
      .then(([suppliers, purchases]) => {
        if (!controller.signal.aborted) setData({ suppliers, purchases });
      })
      .catch((failure) => { if (!controller.signal.aborted) setError(failure.message); });
    return () => controller.abort();
  }, [attempt]);

  async function run(action) {
    if (busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }

  function saveSupplier(event) {
    event.preventDefault();
    run(async () => {
      const values = { name: supplier.name, email: supplier.email, phone: supplier.phone };
      const saved = await apiRequest(`${base}/suppliers${supplier.id ? `/${supplier.id}` : ""}`, {
        method: supplier.id ? "PUT" : "POST", body: JSON.stringify(values),
      });
      setData((previous) => ({
        ...previous,
        suppliers: [...previous.suppliers.filter((item) => item.id !== saved.id), saved]
          .sort((a, b) => a.name.localeCompare(b.name)),
      }));
      setSupplier(emptySupplier);
      setNotice("Supplier saved.");
    });
  }

  function savePurchase(event) {
    event.preventDefault();
    run(async () => {
      const values = {
        supplier_id: Number(supplierId),
        items: items.map((item) => ({ product_id: Number(item.product_id), quantity: Number(item.quantity) })),
      };
      const content = JSON.stringify(values);
      if (pending.current?.content !== content) {
        pending.current = { content, id: crypto.randomUUID() };
      }
      const purchase = await apiRequest(`${base}/orders`, {
        method: "POST", body: JSON.stringify({ ...values, request_id: pending.current.id }),
      });
      setData((previous) => ({
        ...previous, purchases: [purchase, ...previous.purchases.filter((item) => item.id !== purchase.id)],
      }));
      pending.current = null;
      setItems([emptyItem]);
      setNotice(`Purchase order #PO-${purchase.id} saved.`);
    });
  }

  function complete(purchase, status) {
    const action = status === "received" ? "Receive all items on" : "Cancel";
    if (!window.confirm(`${action} purchase order #PO-${purchase.id}?`)) return;
    run(async () => {
      const saved = await apiRequest(`${base}/orders/${purchase.id}/status`, {
        method: "PUT", body: JSON.stringify({ status }),
      });
      setData((previous) => ({
        ...previous, purchases: previous.purchases.map((item) => item.id === saved.id ? saved : item),
      }));
      if (status === "received") onReceived();
      setNotice(status === "received" ? "Purchase received and stock updated." : "Purchase order cancelled.");
    });
  }

  function updateItem(index, values) {
    setItems((previous) => previous.map((item, i) => i === index ? { ...item, ...values } : item));
  }

  return (
    <>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {!data ? (
        error ? <button className="secondary" onClick={() => {
          setError("");
          setAttempt((previous) => previous + 1);
        }}>Retry</button> : <p role="status">Loading purchasing records…</p>
      ) : (
        <>
          <section className="panel settings-panel workspace-settings">
            <h3>Suppliers</h3>
            <form className="workspace-form" onSubmit={saveSupplier}>
              <label>Name<input required maxLength={150} disabled={busy} value={supplier.name}
                onChange={(event) => setSupplier({ ...supplier, name: event.target.value })} /></label>
              <label>Email (optional)<input type="email" maxLength={254} disabled={busy} value={supplier.email}
                onChange={(event) => setSupplier({ ...supplier, email: event.target.value })} /></label>
              <label>Phone (optional)<input type="tel" maxLength={40} disabled={busy} value={supplier.phone}
                onChange={(event) => setSupplier({ ...supplier, phone: event.target.value })} /></label>
              <button className="primary" disabled={busy}>{supplier.id ? "Save supplier" : "Add supplier"}</button>
              {supplier.id && <button type="button" className="secondary" disabled={busy} onClick={() => setSupplier(emptySupplier)}>Cancel edit</button>}
            </form>
            {data.suppliers.length === 0 ? <p>No suppliers yet.</p> : (
              <div className="table-scroll"><table>
                <thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>Actions</th></tr></thead>
                <tbody>{data.suppliers.map((item) => (
                  <tr key={item.id}><td>{item.name}</td><td>{item.email || "—"}</td><td>{item.phone || "—"}</td>
                    <td><button className="secondary" type="button" disabled={busy} onClick={() => setSupplier(item)}>Edit</button></td>
                  </tr>
                ))}</tbody>
              </table></div>
            )}
          </section>

          <section className="panel settings-panel workspace-settings">
            <h3>New purchase order</h3>
            {!productsReady || !products.length || !data.suppliers.length ? (
              <p>A loaded product catalog and at least one supplier are needed to create a purchase order.</p>
            ) : (
              <form onSubmit={savePurchase}>
                <div className="workspace-form">
                  <label>Supplier<select required value={supplierId} disabled={busy} onChange={(event) => setSupplierId(event.target.value)}>
                    <option value="">Select supplier</option>
                    {data.suppliers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                  </select></label>
                </div>
                {items.map((item, index) => (
                  <div className="workspace-form" key={index}>
                    <label>Product<select required disabled={busy} value={item.product_id}
                      onChange={(event) => updateItem(index, { product_id: event.target.value })}>
                      <option value="">Select product</option>
                      {products.map((product) => (
                        <option key={product.id} value={product.id}
                          disabled={items.some((other, i) => i !== index && Number(other.product_id) === product.id)}>{product.name}</option>
                      ))}
                    </select></label>
                    <label>Units<input type="number" min={1} max={Number.MAX_SAFE_INTEGER} required disabled={busy}
                      value={item.quantity} onChange={(event) => updateItem(index, { quantity: event.target.value })} /></label>
                    {items.length > 1 && <button className="secondary" type="button" disabled={busy}
                      onClick={() => setItems((previous) => previous.filter((_, i) => i !== index))}>Remove item</button>}
                  </div>
                ))}
                <div className="sales-actions">
                  <button className="secondary" type="button" disabled={busy || items.length >= Math.min(50, products.length)}
                    onClick={() => setItems((previous) => [...previous, emptyItem])}>Add item</button>
                  <button className="primary" disabled={busy}>Save purchase order</button>
                </div>
              </form>
            )}
          </section>

          <section className="panel settings-panel workspace-settings">
            <h3>Purchase orders</h3>
            {data.purchases.length === 0 ? <p>No purchase orders yet.</p> : (
              <div className="table-scroll"><table>
                <thead><tr><th>Order</th><th>Supplier</th><th>Items</th><th>Status</th><th>Actions</th></tr></thead>
                <tbody>{data.purchases.map((item) => (
                  <tr key={item.id}>
                    <td>#PO-{item.id}</td><td>{item.supplier_name}</td>
                    <td>{item.items.map((line) => <div key={line.product_id}>{line.quantity} × {line.product_name}</div>)}</td>
                    <td>{statuses[item.status]}</td><td>{item.status === "ordered" && (
                      <>
                        <button className="secondary" type="button" disabled={busy} onClick={() => complete(item, "received")}>Receive all</button>{" "}
                        <button className="secondary" type="button" disabled={busy} onClick={() => complete(item, "cancelled")}>Cancel order</button>
                      </>
                    )}</td>
                  </tr>
                ))}</tbody>
              </table></div>
            )}
          </section>
        </>
      )}
    </>
  );
}
