import React, { useEffect, useState } from "react";
import { getPublicStorefront } from "./api";
import StorefrontInquiryForm from "./StorefrontInquiryForm";

export default function PublicStorefront({ slug }) {
  const [storefront, setStorefront] = useState(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getPublicStorefront(slug, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setStorefront(data);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) {
          setError(failure.status === 404 ? "This storefront is unavailable." : "Could not load this storefront.");
        }
      });
    return () => controller.abort();
  }, [slug, attempt]);

  if (!storefront) {
    return (
      <main className="content public-store">
        {error ? (
          <>
            <p role="alert">{error}</p>
            <button className="secondary" onClick={() => {
              setError("");
              setAttempt((previous) => previous + 1);
            }}>Retry</button>
          </>
        ) : (
          <p role="status">Loading storefront…</p>
        )}
      </main>
    );
  }

  const { name, headline, accent_color: accentColor, products } = storefront;
  return (
    <main className="content public-store">
      <article className="panel storefront">
        <header className="store-header"><strong>{name || "Storefront"}</strong></header>
        <section className="store-hero" style={{ background: `linear-gradient(135deg, ${accentColor}20, #f8f5ff)` }}>
          <h1>{headline || "Welcome to our store"}</h1>
          {products.length > 0 && (
            <a href="#catalog" className="store-button" style={{ background: accentColor }}>Browse products</a>
          )}
        </section>
        <section id="catalog" aria-labelledby="catalog-title">
          <h2 id="catalog-title">Products</h2>
          {products.length === 0 ? (
            <p className="empty">No products are listed yet.</p>
          ) : (
            <div className="store-products">
              {products.map((product, index) => (
                <div key={index}>
                  <strong>{product.name}</strong>
                  <small>₹{product.price.toLocaleString("en-IN")}</small>
                </div>
              ))}
            </div>
          )}
        </section>
        {storefront.accept_inquiries && <StorefrontInquiryForm slug={slug} accentColor={accentColor} />}
      </article>
    </main>
  );
}
