export const orderStatuses = ["Pending", "Paid", "Cancelled", "Refunded"];

export function filterOrders(orders, search, status) {
  const query = search.normalize("NFC").trim().toLowerCase();
  const orderNumber = /^#?(?:ord-)?([0-9]+)$/.exec(query);
  const exactId = orderNumber?.[1].replace(/^0+(?=\d)/, "");
  const terms = query.split(/\s+/).filter(Boolean);

  return orders.filter((order) => {
    if (status && order.status !== status) return false;
    if (!terms.length) return true;
    if (exactId !== undefined) return String(order.id) === exactId;

    const fields = [order.customer, ...order.items.map((item) => item.product)]
      .map((field) => field.normalize("NFC").toLowerCase());
    return terms.every((term) => fields.some((field) => field.includes(term)));
  });
}
