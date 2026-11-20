import React, { useLayoutEffect, useRef } from "react";
import { X } from "lucide-react";
import { downloadCsv } from "./csvDownload";
import { restockCsv } from "./restock";

export default function RestockDialog({ items, onClose }) {
  const dialog = useRef(null);
  useLayoutEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => element.close();
  }, []);

  return (
    <dialog className="modal order-details" ref={dialog} aria-labelledby="restock-title"
      onClose={(event) => { if (!event.currentTarget.open) onClose(); }}>
      <div className="modal-title">
        <h3 id="restock-title">Restock list</h3>
        <button type="button" aria-label="Close restock list" onClick={() => dialog.current.close()}>
          <X size={20} aria-hidden="true" />
        </button>
      </div>
      {items.length === 0 ? (
        <p>No products are below their low-stock threshold.</p>
      ) : (
        <>
          <p>Products below their threshold, with the units needed to reach target stock.</p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr><th>Product</th><th>Stock</th><th>Threshold</th><th>Target</th><th>Units to order</th></tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td><strong>{item.name}</strong>{item.category && <div className="muted">{item.category}</div>}</td>
                    <td>{item.stock}</td><td>{item.threshold}</td><td>{item.target}</td>
                    <td><strong>{item.units}</strong></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <button className="secondary restock-export" type="button"
            onClick={() => downloadCsv(restockCsv(items), "vyapari-restock.csv")}>Export restock CSV</button>
        </>
      )}
    </dialog>
  );
}
