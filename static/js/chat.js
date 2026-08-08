/** DRUVO Chat — floating customer assistant with live catalogue + basket awareness. */

import { addToCart, formatGBP, getCart } from "./cart.js";

const STORAGE_KEY = "druvo_chat_history_v1";
const SLUGS_KEY = "druvo_chat_last_slugs_v1";
const MOBILE_MQL = window.matchMedia("(max-width: 640px)");

const root = document.getElementById("druvo-chat-root");
if (!root) {
  // Widget not on page
} else {
  const launcher = document.getElementById("druvo-chat-launcher");
  const panel = document.getElementById("druvo-chat-panel");
  const closeBtn = document.getElementById("druvo-chat-close");
  const messagesEl = document.getElementById("druvo-chat-messages");
  const form = document.getElementById("druvo-chat-form");
  const input = document.getElementById("druvo-chat-input");
  const sendBtn = document.getElementById("druvo-chat-send");

  let history = loadHistory();
  let lastProductSlugs = loadSlugs();
  let welcomeShown = false;
  let sending = false;

  function loadHistory() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  }

  function loadSlugs() {
    try {
      const raw = sessionStorage.getItem(SLUGS_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch {
      return [];
    }
  }

  function saveHistory() {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-16)));
    } catch {
      /* ignore */
    }
  }

  function saveSlugs() {
    try {
      sessionStorage.setItem(SLUGS_KEY, JSON.stringify(lastProductSlugs.slice(-5)));
    } catch {
      /* ignore */
    }
  }

  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatReply(text) {
    const safe = escapeHtml(text);
    return safe
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\n/g, "<br>");
  }

  function renderProductCards(products, bubble) {
    if (!products || !products.length) return;
    products.forEach((product) => {
      const card = document.createElement("article");
      card.className = "druvo-chat-product-card";
      card.dataset.slug = product.slug || "";
      const price = formatGBP(Number(product.price_gbp || 0));
      const was =
        product.is_on_sale && product.compare_at_price_gbp
          ? `<span class="druvo-chat-card-was">${formatGBP(Number(product.compare_at_price_gbp))}</span>`
          : "";
      const sizes = (product.sizes || []).slice(0, 6).join(", ");
      const colours = (product.colours || []).slice(0, 6).join(", ");
      const stock = product.in_stock ? "In stock" : "Out of stock";
      card.innerHTML = `
        <img src="${escapeHtml(product.image || "")}" alt="" loading="lazy" />
        <div class="druvo-chat-product-body">
          <h3>${escapeHtml(product.name || "")}</h3>
          <p class="druvo-chat-product-price">${price} ${was}</p>
          <p class="druvo-chat-product-meta">${escapeHtml(stock)}${sizes ? ` · Sizes: ${escapeHtml(sizes)}` : ""}${colours ? ` · ${escapeHtml(colours)}` : ""}</p>
          <div class="druvo-chat-product-actions">
            <a class="btn btn-secondary btn-sm" href="${escapeHtml(product.url || `/product/${product.slug}`)}" target="_blank" rel="noopener">View Product</a>
            ${product.in_stock ? `<button type="button" class="btn btn-primary btn-sm druvo-chat-add-cart">Add to Basket</button>` : ""}
          </div>
        </div>`;
      const addBtn = card.querySelector(".druvo-chat-add-cart");
      if (addBtn) {
        addBtn.addEventListener("click", () => {
          addToCart({
            slug: product.slug,
            sku: product.sku || "",
            variant_id: product.variant_id ?? null,
            name: product.name,
            size: (product.sizes && product.sizes[0]) || "",
            colour: (product.colours && product.colours[0]) || "",
            price_gbp: Number(product.price_gbp || 0),
            quantity: 1,
          });
          appendMessage("assistant", `Added **${product.name}** to your basket.`);
        });
      }
      bubble.appendChild(card);
    });
  }

  function appendMessage(role, content, products = []) {
    const bubble = document.createElement("div");
    bubble.className = `druvo-chat-bubble druvo-chat-bubble--${role}`;
    bubble.innerHTML = formatReply(content);
    if (role === "assistant" && products.length) {
      renderProductCards(products, bubble);
    }
    messagesEl.appendChild(bubble);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function renderHistory() {
    messagesEl.innerHTML = "";
    for (const item of history) {
      appendMessage(item.role === "user" ? "user" : "assistant", item.content, item.products || []);
    }
  }

  function isMobileViewport() {
    return MOBILE_MQL.matches;
  }

  function setOpen(open) {
    panel.hidden = !open;
    root.classList.toggle("druvo-chat-open", open);
    launcher.setAttribute("aria-expanded", open ? "true" : "false");
    document.body.classList.toggle("druvo-chat-mobile-open", open && isMobileViewport());
    if (open) {
      if (!welcomeShown && history.length === 0) {
        showWelcome();
      } else {
        renderHistory();
      }
      input.focus();
    } else {
      input.blur();
    }
  }

  async function showWelcome() {
    welcomeShown = true;
    try {
      const res = await fetch("/api/chat/status");
      if (res.ok) {
        const data = await res.json();
        appendMessage("assistant", data.welcome || "Hello! How can I help you today?");
        return;
      }
    } catch {
      /* fall through */
    }
    appendMessage(
      "assistant",
      "Hello! I'm DRUVO Chat. Ask me about products, delivery, returns, or current offers."
    );
  }

  function cartPayload() {
    return getCart().map((item) => ({
      slug: item.slug,
      sku: item.sku || "",
      name: item.name || "",
      size: item.size || "",
      colour: item.colour || "",
      price_gbp: Number(item.price_gbp || 0),
      quantity: Number(item.quantity || 1),
      variant_id: item.variant_id ?? null,
    }));
  }

  async function sendMessage(text) {
    if (sending) return;
    const trimmed = text.trim();
    if (!trimmed) return;

    sending = true;
    sendBtn.disabled = true;
    input.disabled = true;

    appendMessage("user", trimmed);
    history.push({ role: "user", content: trimmed });
    saveHistory();

    const typing = document.createElement("div");
    typing.className = "druvo-chat-bubble druvo-chat-bubble--assistant druvo-chat-typing";
    typing.textContent = "DRUVO Chat is typing…";
    messagesEl.appendChild(typing);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    try {
      const res = await fetch("/api/chat/message", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: trimmed,
          history: history.slice(0, -1).slice(-8),
          cart: cartPayload(),
          last_product_slugs: lastProductSlugs,
        }),
      });

      typing.remove();

      if (res.status === 429) {
        appendMessage(
          "assistant",
          "You're sending messages quite quickly. Please wait a moment and try again."
        );
        return;
      }

      if (!res.ok) {
        appendMessage(
          "assistant",
          "Sorry, I'm having trouble right now. Please email druvo.uk@gmail.com and we'll help you."
        );
        return;
      }

      const data = await res.json();
      const reply = data.reply || "I'm not sure about that. Please contact us at druvo.uk@gmail.com.";
      const products = data.products || [];
      if (data.context_product_slugs && data.context_product_slugs.length) {
        lastProductSlugs = data.context_product_slugs;
        saveSlugs();
      }
      appendMessage("assistant", reply, products);
      history.push({ role: "assistant", content: reply, products });
      saveHistory();
    } catch {
      typing.remove();
      appendMessage(
        "assistant",
        "Connection issue — please try again or email druvo.uk@gmail.com."
      );
    } finally {
      sending = false;
      sendBtn.disabled = false;
      input.disabled = false;
      input.value = "";
      input.focus();
    }
  }

  launcher.addEventListener("click", () => setOpen(panel.hidden));
  closeBtn.addEventListener("click", () => setOpen(false));

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) {
      setOpen(false);
    }
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(input.value);
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage(input.value);
    }
  });

  // Closed by default on every page load — history persists, open state does not.
  setOpen(false);

  MOBILE_MQL.addEventListener("change", () => {
    if (!panel.hidden && !isMobileViewport()) {
      document.body.classList.remove("druvo-chat-mobile-open");
    }
  });
}
