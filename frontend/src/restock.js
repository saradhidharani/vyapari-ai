export function restockList(products) {
  return products.flatMap((product) => {
    const threshold = product.low_stock_threshold ?? 10;
    if (product.stock >= threshold) return [];
    const target = product.restock_target ?? threshold;
    return [{ ...product, threshold, target, units: target - product.stock }];
  }).sort((first, second) => second.units - first.units || first.name.localeCompare(second.name));
}

function csvText(value) {
  const text = /^[\t\r\n]|^[\s\uFEFF]*[=+\-@＝＋－＠]/u.test(value) ? "'" + value : value;
  return `"${text.replaceAll('"', '""')}"`;
}

export function restockCsv(items) {
  return [
    "Product,Category,Stock,Low-stock threshold,Target stock,Units to order",
    ...items.map((item) => [
      csvText(item.name), csvText(item.category), item.stock, item.threshold, item.target, item.units,
    ].join(",")),
    "",
  ].join("\r\n");
}
