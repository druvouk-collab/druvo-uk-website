import { formatGBP, getCart } from "./cart.js";

function renderSummary() {
  const summary = document.getElementById("checkout-summary");
  if (!summary) return;
  const cart = getCart();
  if (!cart.length) {
    summary.innerHTML = `<p class="product-meta">Your basket is empty. <a href="/shop">Continue shopping</a>.</p>`;
    document.getElementById("place-order")?.setAttribute("disabled", "disabled");
    return;
  }
  const rows = cart
    .map(
      (item) =>
        `<div class="summary-row"><span>${item.name} · ${item.colour}/${item.size} × ${item.quantity}</span><span>${formatGBP(item.price_gbp * item.quantity)}</span></div>`
    )
    .join("");
  const subtotal = cart.reduce((sum, item) => sum + item.price_gbp * item.quantity, 0);
  summary.innerHTML = `
    ${rows}
    <div class="summary-row total"><span>Subtotal</span><span>${formatGBP(subtotal)}</span></div>`;
}

async function placeOrder() {
  const ready = document.getElementById("checkout-summary")?.dataset.checkoutReady === "true";
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

  button.disabled = true;
  status.textContent = "Checking stock with DRUVO AI…";
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
