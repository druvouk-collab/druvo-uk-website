const CART_KEY = "druvo_uk_cart";

export function getCart() {
  try {
    return JSON.parse(localStorage.getItem(CART_KEY) || "[]");
  } catch {
    return [];
  }
}

export function saveCart(items) {
  localStorage.setItem(CART_KEY, JSON.stringify(items));
  updateCartBadge();
  document.dispatchEvent(new CustomEvent("druvo:cart-updated", { detail: items }));
}

export function updateCartBadge() {
  const count = getCart().reduce((sum, item) => sum + item.quantity, 0);
  document.querySelectorAll("[data-cart-count]").forEach((el) => {
    el.textContent = String(count);
    el.hidden = count === 0;
  });
}

export function addToCart(item) {
  const cart = getCart();
  const existing = cart.find(
    (row) =>
      (item.sku && row.sku === item.sku) ||
      (row.slug === item.slug && row.size === item.size && row.colour === item.colour)
  );
  if (existing) {
    existing.quantity += item.quantity;
    existing.sku = item.sku || existing.sku;
    existing.variant_id = item.variant_id ?? existing.variant_id ?? null;
  } else {
    cart.push(item);
  }
  saveCart(cart);
}

export function removeFromCart(index) {
  const cart = getCart();
  cart.splice(index, 1);
  saveCart(cart);
}

export function updateCartQuantity(index, quantity) {
  const cart = getCart();
  if (!cart[index]) return;
  const qty = Math.max(1, Number(quantity) || 1);
  cart[index].quantity = qty;
  saveCart(cart);
}

export function formatGBP(value) {
  return new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" }).format(value);
}

document.addEventListener("DOMContentLoaded", () => {
  updateCartBadge();

  const menuToggle = document.querySelector("[data-menu-toggle]");
  const mobileNav = document.querySelector("[data-mobile-nav]");
  if (menuToggle && mobileNav) {
    menuToggle.addEventListener("click", () => {
      const open = mobileNav.classList.toggle("open");
      menuToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }
});
