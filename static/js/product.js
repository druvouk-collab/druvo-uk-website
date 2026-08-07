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
    return variants.find((v) => v.size === selectedSize && v.colour === selectedColour) || null;
  }

  function comboInStock(size, colour) {
    const variant = variants.find((v) => v.size === size && v.colour === colour);
    return Boolean(variant && variant.stock_quantity > 0);
  }

  function firstInStockCombo() {
    return variants.find((v) => v.stock_quantity > 0) || null;
  }

  function ensureValidSelection() {
    if (comboInStock(selectedSize, selectedColour)) return;
    const fallback = firstInStockCombo();
    if (fallback) {
      selectedSize = fallback.size;
      selectedColour = fallback.colour;
      return;
    }
    selectedSize = "";
    selectedColour = "";
  }

  function refreshVariantButtons() {
    document.querySelectorAll("[data-variant-size]").forEach((btn) => {
      const size = btn.dataset.variantSize;
      const enabled = selectedColour
        ? comboInStock(size, selectedColour)
        : variants.some((v) => v.size === size && v.stock_quantity > 0);
      btn.disabled = !enabled;
      btn.classList.toggle("active", size === selectedSize);
    });
    document.querySelectorAll("[data-variant-colour]").forEach((btn) => {
      const colour = btn.dataset.variantColour;
      const enabled = selectedSize
        ? comboInStock(selectedSize, colour)
        : variants.some((v) => v.colour === colour && v.stock_quantity > 0);
      btn.disabled = !enabled;
      btn.classList.toggle("active", colour === selectedColour);
    });
  }

  function refreshUI() {
    ensureValidSelection();
    refreshVariantButtons();

    const variant = currentVariant();
    if (!variant || variant.stock_quantity <= 0) {
      priceEl.textContent = "—";
      stockEl.textContent = variant && variant.stock_quantity <= 0 ? "Out of stock" : "Select size and colour";
      stockEl.className = "stock-note";
      addBtn.disabled = true;
      qtyInput.max = 1;
      return;
    }

    const price = root.dataset.onSale === "true" ? Number(root.dataset.salePrice) : variant.price_gbp;
    priceEl.textContent = formatGBP(price);
    stockEl.textContent = `${variant.stock_quantity} in stock`;
    stockEl.className = "stock-note in-stock";
    addBtn.disabled = false;
    quantity = Math.min(Math.max(1, quantity), variant.stock_quantity);
    qtyInput.value = quantity;
    qtyInput.max = variant.stock_quantity;
  }

  document.querySelectorAll("[data-variant-size]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      selectedSize = btn.dataset.variantSize;
      if (selectedColour && !comboInStock(selectedSize, selectedColour)) {
        const nextColour = variants.find(
          (v) => v.size === selectedSize && v.stock_quantity > 0
        );
        selectedColour = nextColour ? nextColour.colour : "";
      }
      refreshUI();
    });
  });
  document.querySelectorAll("[data-variant-colour]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.disabled) return;
      selectedColour = btn.dataset.variantColour;
      if (selectedSize && !comboInStock(selectedSize, selectedColour)) {
        const nextSize = variants.find(
          (v) => v.colour === selectedColour && v.stock_quantity > 0
        );
        selectedSize = nextSize ? nextSize.size : "";
      }
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
    const variant = currentVariant();
    const maxQty = variant ? variant.stock_quantity : 1;
    quantity = Math.min(maxQty, quantity + 1);
    qtyInput.value = quantity;
  });
  qtyInput?.addEventListener("change", () => {
    const variant = currentVariant();
    const maxQty = variant ? variant.stock_quantity : 1;
    quantity = Math.max(1, Math.min(maxQty, Number(qtyInput.value || 1)));
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
      variant_id: variant.variant_id ?? null,
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
          <p class="product-meta">SKU ${item.sku}</p>
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
