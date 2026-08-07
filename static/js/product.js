import { addToCart, formatGBP, getCart, removeFromCart, saveCart, updateCartQuantity } from "./cart.js";
import { initImageFallbacks } from "./images.js";

const PLACEHOLDER = "/static/images/placeholder-product.svg";

function initProductPage() {
  const root = document.querySelector("[data-product-page]");
  if (!root) return;

  const variants = JSON.parse(root.dataset.variants || "[]");
  let selectedSize = root.dataset.defaultSize || "";
  let selectedColour = root.dataset.defaultColour || "";
  let quantity = 1;

  const mainImage = document.querySelector("[data-gallery-main]");
  const priceEl = document.querySelector("[data-product-price]");
  const stockEl = document.querySelector("[data-stock-note]");
  const qtyInput = document.querySelector("[data-qty-input]");
  const addBtn = document.querySelector("[data-add-to-cart]");

  function currentVariant() {
    return variants.find((v) => v.size === selectedSize && v.colour === selectedColour);
  }

  function refreshUI() {
    const variant = currentVariant();
    document.querySelectorAll("[data-variant-size]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.variantSize === selectedSize);
    });
    document.querySelectorAll("[data-variant-colour]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.variantColour === selectedColour);
    });

    if (!variant) {
      priceEl.textContent = "—";
      stockEl.textContent = "Select size and colour";
      stockEl.className = "stock-note";
      addBtn.disabled = true;
      return;
    }

    const price = root.dataset.onSale === "true" ? Number(root.dataset.salePrice) : variant.price_gbp;
    priceEl.textContent = formatGBP(price);
    if (variant.stock_quantity > 0) {
      stockEl.textContent = `${variant.stock_quantity} in stock`;
      stockEl.className = "stock-note in-stock";
      addBtn.disabled = false;
    } else {
      stockEl.textContent = "Out of stock";
      stockEl.className = "stock-note";
      addBtn.disabled = true;
    }
    qtyInput.max = Math.max(variant.stock_quantity, 1);
  }

  document.querySelectorAll("[data-variant-size]").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedSize = btn.dataset.variantSize;
      refreshUI();
    });
  });
  document.querySelectorAll("[data-variant-colour]").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedColour = btn.dataset.variantColour;
      refreshUI();
    });
  });
  document.querySelectorAll("[data-gallery-thumb]").forEach((btn) => {
    btn.addEventListener("click", () => {
      mainImage.src = btn.dataset.galleryThumb;
      document.querySelectorAll("[data-gallery-thumb]").forEach((el) => el.classList.remove("active"));
      btn.classList.add("active");
    });
  });
  document.querySelector("[data-qty-minus]")?.addEventListener("click", () => {
    quantity = Math.max(1, quantity - 1);
    qtyInput.value = quantity;
  });
  document.querySelector("[data-qty-plus]")?.addEventListener("click", () => {
    quantity += 1;
    qtyInput.value = quantity;
  });
  qtyInput?.addEventListener("change", () => {
    quantity = Math.max(1, Number(qtyInput.value || 1));
    qtyInput.value = quantity;
  });
  addBtn?.addEventListener("click", () => {
    const variant = currentVariant();
    if (!variant || variant.stock_quantity <= 0) return;
    const price = root.dataset.onSale === "true" ? Number(root.dataset.salePrice) : variant.price_gbp;
    addToCart({
      slug: root.dataset.slug,
      name: root.dataset.name,
      image: root.dataset.image,
      size: variant.size,
      colour: variant.colour,
      sku: variant.sku,
      price_gbp: price,
      quantity,
    });
    addBtn.textContent = "Added to basket";
    setTimeout(() => { addBtn.textContent = "Add to basket"; }, 1200);
  });

  refreshUI();
}

function renderCartPage() {
  const list = document.querySelector("[data-cart-list]");
  const empty = document.querySelector("[data-cart-empty]");
  const summary = document.querySelector("[data-cart-summary]");
  if (!list || !summary) return;

  const cart = getCart();
  if (!cart.length) {
    list.innerHTML = "";
    empty.hidden = false;
    summary.innerHTML = "";
    return;
  }
  empty.hidden = true;
  list.innerHTML = cart
    .map(
      (item, index) => `
      <article class="cart-item">
        <img class="druvo-img" src="${item.image}" alt="" data-placeholder="${PLACEHOLDER}">
        <div>
          <strong>${item.name}</strong>
          <p class="product-meta">${item.colour} · ${item.size}</p>
          <div class="cart-qty-row">
            <div class="qty-control">
              <button type="button" data-cart-qty-minus="${index}" aria-label="Decrease quantity">−</button>
              <input type="number" min="1" value="${item.quantity}" data-cart-qty-input="${index}" aria-label="Quantity">
              <button type="button" data-cart-qty-plus="${index}" aria-label="Increase quantity">+</button>
            </div>
            <span>${formatGBP(item.price_gbp)} each</span>
          </div>
          <button class="btn btn-ghost" data-remove-index="${index}">Remove</button>
        </div>
        <div><strong>${formatGBP(item.price_gbp * item.quantity)}</strong></div>
      </article>`
    )
    .join("");

  const subtotal = cart.reduce((sum, item) => sum + item.price_gbp * item.quantity, 0);
  const shipping = subtotal >= 75 ? 0 : 3.99;
  summary.innerHTML = `
    <div class="summary-row"><span>Subtotal</span><span>${formatGBP(subtotal)}</span></div>
    <div class="summary-row"><span>Shipping (UK)</span><span>${shipping === 0 ? "Free" : formatGBP(shipping)}</span></div>
    <div class="summary-row total"><span>Total</span><span>${formatGBP(subtotal + shipping)}</span></div>
    <a class="btn btn-primary" href="/checkout" style="width:100%;margin-top:1rem;">Proceed to checkout</a>`;

  list.querySelectorAll("[data-remove-index]").forEach((btn) => {
    btn.addEventListener("click", () => {
      removeFromCart(Number(btn.dataset.removeIndex));
      renderCartPage();
    });
  });

  list.querySelectorAll("[data-cart-qty-minus]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const index = Number(btn.dataset.cartQtyMinus);
      const cart = getCart();
      updateCartQuantity(index, Math.max(1, cart[index].quantity - 1));
      renderCartPage();
    });
  });

  list.querySelectorAll("[data-cart-qty-plus]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const index = Number(btn.dataset.cartQtyPlus);
      const cart = getCart();
      updateCartQuantity(index, cart[index].quantity + 1);
      renderCartPage();
    });
  });

  list.querySelectorAll("[data-cart-qty-input]").forEach((input) => {
    input.addEventListener("change", () => {
      updateCartQuantity(Number(input.dataset.cartQtyInput), input.value);
      renderCartPage();
    });
  });

  initImageFallbacks(list);
}

document.addEventListener("DOMContentLoaded", () => {
  initProductPage();
  renderCartPage();
});

document.addEventListener("druvo:cart-updated", renderCartPage);
