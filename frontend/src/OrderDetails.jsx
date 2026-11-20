import React, { useLayoutEffect, useRef } from "react";
import { X } from "lucide-react";

const price = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" });
const timestamp = new Intl.DateTimeFormat("en-IN", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Kolkata",
});

function amount(paise) {
  return price.format(paise / 100);
}

export default function OrderDetails({ order, onClose }) {
  const dialog = useRef(null);
  useLayoutEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);

  const events = [
    ["Order recorded", order.date],
    ["Payment recorded", order.paid_at],
    ["Order cancelled", order.cancelled_at],
    ["Refund recorded", order.refunded_at],
  ].filter(([, date]) => date);

  return (
    <dialog
      className="modal order-details"
      ref={dialog}
      aria-labelledby="order-details-title"
      onClose={(event) => {
        if (!event.currentTarget.open) onClose();
      }}
    >
      <div className="modal-title">
        <h3 id="order-details-title">Order #ORD-{order.id}</h3>
        <button type="button" aria-label="Close order details" onClick={() => dialog.current.close()}>
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      <div className="order-details-customer">
        <strong>{order.customer}</strong>
        <span className={`status ${order.status.toLowerCase()}`}>{order.status}</span>
      </div>
      {order.source_inquiry_id && (
        <p className="muted">Website enquiry #{order.source_inquiry_id} · {order.source_website_label}</p>
      )}

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Product</th>
              <th scope="col">Qty</th>
              <th scope="col">Unit price</th>
              <th scope="col">Line total</th>
            </tr>
          </thead>
          <tbody>
            {order.items.map((item) => (
              <tr key={item.product_id}>
                <td>{item.product}</td>
                <td>{item.quantity}</td>
                <td>{amount(item.unit_price_paise)}</td>
                <td>{amount(item.unit_price_paise * item.quantity)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row" colSpan={3}>Order total</th>
              <td><strong>{amount(order.amount_paise)}</strong></td>
            </tr>
          </tfoot>
        </table>
      </div>

      <h4>Order history <span className="muted">(IST)</span></h4>
      <dl className="order-history">
        {events.map(([label, date]) => (
          <React.Fragment key={label}>
            <dt>{label}</dt>
            <dd><time dateTime={date}>{timestamp.format(new Date(date))}</time></dd>
          </React.Fragment>
        ))}
      </dl>
      {order.refunded_at && (
        <p className="muted">{order.refund_restocked ? "Refunded items returned to stock." : "Refund recorded without returning items to stock."}</p>
      )}
    </dialog>
  );
}
