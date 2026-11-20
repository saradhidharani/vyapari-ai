import React, { useState } from "react";
import { X } from "lucide-react";
import { createOrder } from "./api";

const emptyLine = { product_id: "", quantity: "1" };

export default function OrderForm({ customers, products, inquiry, onSave, onClose }) {
  const [customerId, setCustomerId] = useState(inquiry?.customer_id == null ? "" : String(inquiry.customer_id));
  const [items, setItems] = useState([emptyLine]);
  const [status, setStatus] = useState("Pending");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [requestId] = useState(() => crypto.randomUUID());
  const [attemptedOrder, setAttemptedOrder] = useState(null);

  function editLine(index, changes) {
    setItems((previous) => previous.map((item, i) => i === index ? { ...item, ...changes } : item));
  }

  async function save(event) {
    event.preventDefault();
    if (busy) return;
    const payload = attemptedOrder ?? {
      request_id: requestId,
      customer_id: Number(customerId),
      status,
      ...(inquiry && { source_inquiry_id: inquiry.id }),
      items: items.map((item) => ({
        product_id: Number(item.product_id),
        quantity: Number(item.quantity),
      })),
    };
    setBusy(true);
    setError("");
    try {
      onSave(await createOrder(payload));
    } catch (failure) {
      setError(`Could not save order. ${failure.message}`);
      // A lost response can leave a saved order. Retry the same request.
      setAttemptedOrder(!failure.status || failure.status >= 500 ? payload : null);
    } finally {
      setBusy(false);
    }
  }

  const locked = busy || Boolean(attemptedOrder);

  return (
    <div className="modal-backdrop" onClick={() => !busy && !attemptedOrder && onClose()}>
      <form className="modal" style={{ maxHeight: "90vh", overflowY: "auto" }} onClick={(event) => event.stopPropagation()} onSubmit={save}>
        <div className="modal-title">
          <h3>New order</h3>
          <button type="button" disabled={busy} aria-label="Close" onClick={onClose}><X /></button>
        </div>
        <label>
          Customer
          <select className="order-select" required disabled={locked || Boolean(inquiry)} value={customerId} onChange={(event) => setCustomerId(event.target.value)}>
            <option value="">Select customer</option>
            {customers.map((customer) => (
              <option key={customer.id} value={customer.id}>
                {customer.name}{customer.phone ? ` · ${customer.phone}` : customer.email ? ` · ${customer.email}` : ""}
              </option>
            ))}
          </select>
        </label>
        {inquiry && <p className="muted">Website enquiry #{inquiry.id} · {inquiry.website_label}</p>}
        {items.map((item, index) => (
          <div key={index}>
            <label>
              Product
              <select className="order-select" required disabled={locked} value={item.product_id} onChange={(event) => editLine(index, { product_id: event.target.value })}>
                <option value="">Select product</option>
                {products.map((product) => (
                  <option key={product.id} value={product.id} disabled={items.some((line, i) => i !== index && Number(line.product_id) === product.id)}>
                    {product.name} · ₹{product.price} · {product.stock} in stock
                  </option>
                ))}
              </select>
            </label>
            <label>
              Quantity
              <input type="number" min={1} max={products.find((product) => product.id === Number(item.product_id))?.stock} required disabled={locked} value={item.quantity} onChange={(event) => editLine(index, { quantity: event.target.value })} />
            </label>
            {items.length > 1 && (
              <button className="text-button" type="button" disabled={locked} onClick={() => setItems((previous) => previous.filter((_, i) => i !== index))}>
                Remove item
              </button>
            )}
          </div>
        ))}
        <button className="secondary" type="button" disabled={locked || items.length >= Math.min(50, products.length)} onClick={() => setItems((previous) => [...previous, emptyLine])}>
          Add item
        </button>
        <label>
          Payment status
          <select className="order-select" disabled={locked} value={status} onChange={(event) => setStatus(event.target.value)}>
            <option>Pending</option>
            <option>Paid</option>
          </select>
        </label>
        {error && <p role="alert">{error}</p>}
        {attemptedOrder && <p>Retry this save before starting another order for the same sale.</p>}
        <button className="primary" type="submit" disabled={busy}>
          {busy ? "Saving…" : attemptedOrder ? "Retry save" : "Save order"}
        </button>
      </form>
    </div>
  );
}
