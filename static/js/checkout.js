import { formatGBP, getCart, calculateShipping, loadShippingConfig } from "./cart.js";

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]);
}

function variantLabel(item) {
  return [item.colour, item.size].filter(Boolean).join(" / ");
}

export function buildOrderEmail(cart, contactEmail) {
  const lines = cart.map((item, index) => {
    const variant = variantLabel(item);
    const parts = [`${index + 1}. ${item.name}`];
    if (variant) parts.push(`(${variant})`);
    parts.push(`x ${item.quantity}`);
    parts.push(`- ${formatGBP(item.price_gbp)} each`);
    if (item.sku) parts.push(`[SKU ${item.sku}]`);
    return parts.join(" ");
  });
  const subtotal = cart.reduce((sum, item) => sum + item.price_gbp * item.quantity, 0);
  const body = [
    "Hello DRUVO UK,",
    "",
    "I'd like to order:",
    ...lines,
    "",
    `Items subtotal: ${formatGBP(subtotal)} (delivery to be confirmed)`,
    "",
    "Name:",
    "Delivery postcode:",
    "Phone (optional):",
    "",
    "Please confirm stock, the delivery cost and how to pay.",
  ].join("\n");
  const subject = `Order request - ${cart.length} item${cart.length === 1 ? "" : "s"}`;
  return `mailto:${contactEmail}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}

function renderEmailOrder(cart) {
  const panel = document.getElementById("email-order-panel");
  const link = document.getElementById("email-order-link");
  if (!panel || !link) return;
  const contactEmail = panel.dataset.contactEmail;
  if (!cart.length) {
    link.setAttribute("aria-disabled", "true");
    link.classList.add("disabled");
    link.href = "/shop";
    link.textContent = "Browse the shop";
    return;
  }
  link.removeAttribute("aria-disabled");
  link.classList.remove("disabled");
  link.href = buildOrderEmail(cart, contactEmail);
  link.textContent = "Order by email";
}

async function renderSummary() {
  const summary = document.getElementById("checkout-summary");
  if (!summary) return;
  const cart = getCart();
  const emailOrders = summary.dataset.emailOrders === "true";
  if (emailOrders) renderEmailOrder(cart);
  if (!cart.length) {
    summary.innerHTML = `<p class="product-meta">Your basket is empty. <a href="/shop">Continue shopping</a>.</p>`;
    document.getElementById("place-order")?.setAttribute("disabled", "disabled");
    return;
  }
  if (emailOrders) {
    const rows = cart
      .map((item) => {
        const variant = variantLabel(item);
        return `<div class="summary-row"><span>${escapeHtml(item.name)}${variant ? ` · ${escapeHtml(variant)}` : ""} × ${item.quantity}</span><span>${formatGBP(item.price_gbp * item.quantity)}</span></div>`;
      })
      .join("");
    const subtotal = cart.reduce((sum, item) => sum + item.price_gbp * item.quantity, 0);
    summary.innerHTML = `
      ${rows}
      <div class="summary-row total"><span>Items subtotal</span><span>${formatGBP(subtotal)}</span></div>`;
    return;
  }
  await loadShippingConfig();
  const rows = cart
    .map(
      (item) =>
        `<div class="summary-row"><span>${item.name} · ${item.colour}/${item.size} × ${item.quantity}</span><span>${formatGBP(item.price_gbp * item.quantity)}</span></div>`
    )
    .join("");
  const subtotal = cart.reduce((sum, item) => sum + item.price_gbp * item.quantity, 0);
  const quote = calculateShipping(subtotal);
  summary.innerHTML = `
    ${rows}
    <div class="summary-row"><span>Subtotal</span><span>${formatGBP(quote.subtotal)}</span></div>
    <div class="summary-row"><span>Shipping (UK)</span><span>${quote.free ? "Free" : formatGBP(quote.shipping)}</span></div>
    <div class="summary-row total"><span>Total</span><span>${formatGBP(quote.total)}</span></div>`;
}

async function placeOrder() {
  const summary = document.getElementById("checkout-summary");
  const ready = summary?.dataset.checkoutReady === "true";
  const paymentsEnabled = summary?.dataset.paymentsEnabled === "true";
  const status = document.getElementById("checkout-status");
  const button = document.getElementById("place-order");
  const cart = getCart();
  if (!ready || !cart.length) return;

  const email = document.getElementById("email")?.value?.trim();
  const first = document.getElementById("first-name")?.value?.trim();
  const last = document.getElementById("last-name")?.value?.trim();
  if (!email || !first || !last) {
    status.textContent = "Please complete required contact fields.";
    return;
  }

  const lines = cart.map((item) => ({
    sku: item.sku,
    quantity: item.quantity,
    unit_price_gbp: item.price_gbp,
    ...(item.variant_id != null ? { variant_id: item.variant_id } : {}),
  }));

  let externalOrderId = sessionStorage.getItem("druvo_checkout_order_id");
  if (!externalOrderId) {
    externalOrderId = `web-${crypto.randomUUID().replace(/-/g, "").slice(0, 16)}`;
    sessionStorage.setItem("druvo_checkout_order_id", externalOrderId);
  }

  const dbCheckout = summary?.dataset.dbCheckout === "true";
  const phone = document.getElementById("phone")?.value?.trim() || "";
  button.disabled = true;
  status.textContent = dbCheckout ? "Checking availability…" : "Checking stock with DRUVO AI…";
  try {
    const validate = await fetch("/api/checkout/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ customer_email: email, customer_name: `${first} ${last}`.trim(), lines }),
    });
    const validatePayload = await validate.json().catch(() => ({}));
    if (!validate.ok) {
      throw new Error(validatePayload.detail || "Stock check failed.");
    }
    if (!validatePayload.ok) {
      throw new Error("Some items are no longer in stock. Update your basket and try again.");
    }

    if (paymentsEnabled) {
      status.textContent = dbCheckout ? "Holding your items and opening secure payment…" : "Redirecting to secure Stripe checkout (test mode)…";
      const response = await fetch("/api/checkout/payment-session", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          customer_email: email,
          customer_name: `${first} ${last}`.trim(),
          external_order_id: externalOrderId,
          phone,
          lines,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        if (response.status === 409 || response.status === 400) sessionStorage.removeItem("druvo_checkout_order_id");
        throw new Error(payload.detail || "Could not start payment session.");
      }
      window.location.href = payload.checkout_url;
      return;
    }

    status.textContent = "Submitting order to DRUVO AI…";
    const response = await fetch("/api/checkout/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        customer_email: email,
        customer_name: `${first} ${last}`.trim(),
        external_order_id: externalOrderId,
        lines,
      }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || "Order could not be placed.");
    }
    sessionStorage.removeItem("druvo_checkout_order_id");
    localStorage.removeItem("druvo_uk_cart");
    const accountLink = `/account/orders?email=${encodeURIComponent(email)}`;
    status.innerHTML = payload.duplicate
      ? `Order already recorded (duplicate protection). <a href="${accountLink}">View order history</a>.`
      : `Order confirmed — reference #${payload.order_id}. <a href="${accountLink}">View order history</a>.`;
    renderSummary();
  } catch (error) {
    status.textContent = error.message || "Order failed.";
    button.disabled = false;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  renderSummary();
  document.getElementById("place-order")?.addEventListener("click", placeOrder);
});

document.addEventListener("druvo:cart-updated", renderSummary);
