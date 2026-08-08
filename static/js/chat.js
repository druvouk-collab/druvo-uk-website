/** DRUVO Chat — mobile drawer UI, multilingual assistant, live catalogue awareness. */

import { addToCart, formatGBP, getCart } from "./cart.js";

const STORAGE_KEY = "druvo_chat_history_v1";
const SLUGS_KEY = "druvo_chat_last_slugs_v1";
const LOCALE_KEY = "druvo_chat_locale_v1";
const MOBILE_MQL = window.matchMedia("(max-width: 640px)");
const CLOSE_ANIM_MS = 280;

const UI_STRINGS = {
  "en-GB": {
    subtitle: "Online shopping assistant",
    placeholder: "Ask about products, sizes, delivery…",
    send: "Send",
    typing: "DRUVO Chat is typing…",
    chooseLanguage: "Choose your language 🌐",
    moreLanguages: "More languages 🌐",
    searchLanguages: "Search languages…",
    inStock: "In stock",
    outOfStock: "Out of stock",
    viewProduct: "View Product",
    addToBasket: "Add to Basket",
    addedToBasket: "Added **{name}** to your basket.",
    rateLimit: "You're sending messages quite quickly. Please wait a moment and try again.",
    errorGeneric: "Sorry, I'm having trouble right now. Please email druvo.uk@gmail.com and we'll help you.",
    errorConnection: "Connection issue — please try again or email druvo.uk@gmail.com.",
    fallbackWelcome:
      "Hello! I'm DRUVO Chat. Ask me about products, delivery, returns, or current offers.",
  },
};

const root = document.getElementById("druvo-chat-root");
if (!root) {
  // Widget not on page
} else {
  const launcher = document.getElementById("druvo-chat-launcher");
  const backdrop = document.getElementById("druvo-chat-backdrop");
  const panel = document.getElementById("druvo-chat-panel");
  const closeBtn = document.getElementById("druvo-chat-close");
  const langBtn = document.getElementById("druvo-chat-lang-btn");
  const langScreen = document.getElementById("druvo-chat-lang-screen");
  const langQuick = document.getElementById("druvo-chat-lang-quick");
  const langMoreBtn = document.getElementById("druvo-chat-lang-more");
  const langSearchWrap = document.getElementById("druvo-chat-lang-search-wrap");
  const langSearch = document.getElementById("druvo-chat-lang-search");
  const langResults = document.getElementById("druvo-chat-lang-results");
  const subtitleEl = document.getElementById("druvo-chat-subtitle");
  const messagesEl = document.getElementById("druvo-chat-messages");
  const form = document.getElementById("druvo-chat-form");
  const input = document.getElementById("druvo-chat-input");
  const sendBtn = document.getElementById("druvo-chat-send");

  let history = loadHistory();
  let lastProductSlugs = loadSlugs();
  let locale = loadLocale();
  let welcomeShown = false;
  let sending = false;
  let closingTimer = null;
  let languageCatalog = [];
  let languageCatalogLoaded = false;

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

  function loadLocale() {
    try {
      return localStorage.getItem(LOCALE_KEY) || "";
    } catch {
      return "";
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

  function saveLocale(code) {
    locale = code;
    try {
      localStorage.setItem(LOCALE_KEY, code);
    } catch {
      /* ignore */
    }
  }

  function ui(key) {
    const pack = UI_STRINGS["en-GB"];
    return pack[key] || key;
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

  function isMobileViewport() {
    return MOBILE_MQL.matches;
  }

  function applyRtl(rtl) {
    if (rtl) {
      panel.setAttribute("dir", "rtl");
      panel.setAttribute("lang", locale.split("-")[0]);
    } else {
      panel.removeAttribute("dir");
      panel.setAttribute("lang", locale || "en-GB");
    }
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
      const stock = product.in_stock ? ui("inStock") : ui("outOfStock");
      card.innerHTML = `
        <img src="${escapeHtml(product.image || "")}" alt="" loading="lazy" />
        <div class="druvo-chat-product-body">
          <h3>${escapeHtml(product.name || "")}</h3>
          <p class="druvo-chat-product-price">${price} ${was}</p>
          <p class="druvo-chat-product-meta">${escapeHtml(stock)}${sizes ? ` · Sizes: ${escapeHtml(sizes)}` : ""}${colours ? ` · ${escapeHtml(colours)}` : ""}</p>
          <div class="druvo-chat-product-actions">
            <a class="btn btn-secondary btn-sm" href="${escapeHtml(product.url || `/product/${product.slug}`)}" target="_blank" rel="noopener">${ui("viewProduct")}</a>
            ${product.in_stock ? `<button type="button" class="btn btn-primary btn-sm druvo-chat-add-cart">${ui("addToBasket")}</button>` : ""}
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
          appendMessage("assistant", ui("addedToBasket").replace("{name}", product.name || ""));
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

  function showLanguageScreen(show) {
    langScreen.hidden = !show;
    panel.classList.toggle("druvo-chat-lang-open", show);
    if (show) {
      langSearchWrap.hidden = true;
      langSearch.value = "";
      renderQuickLanguages();
    }
  }

  function renderQuickLanguages() {
    langQuick.innerHTML = "";
    const quick = languageCatalog.filter((row) => row.quick);
    quick.forEach((row) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "druvo-chat-lang-option";
      btn.setAttribute("role", "option");
      btn.setAttribute("aria-selected", row.code === locale ? "true" : "false");
      btn.dataset.code = row.code;
      btn.innerHTML = `<span dir="auto">${escapeHtml(row.native || row.name)}</span>`;
      btn.addEventListener("click", () => selectLanguage(row.code, row.rtl));
      langQuick.appendChild(btn);
    });
  }

  function renderLanguageResults(filter = "") {
    langResults.innerHTML = "";
    const term = filter.trim().toLowerCase();
    const matches = languageCatalog.filter((row) => {
      if (!term) return !row.quick;
      const hay = `${row.name} ${row.native} ${row.code}`.toLowerCase();
      return hay.includes(term);
    });
    matches.slice(0, 40).forEach((row) => {
      const li = document.createElement("li");
      const btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("role", "option");
      btn.innerHTML = `<span dir="auto">${escapeHtml(row.native || row.name)}</span> <span class="muted">(${escapeHtml(row.name)})</span>`;
      btn.addEventListener("click", () => selectLanguage(row.code, row.rtl));
      li.appendChild(btn);
      langResults.appendChild(li);
    });
  }

  async function ensureLanguageCatalog() {
    if (languageCatalogLoaded) return;
    try {
      const res = await fetch("/api/chat/languages");
      if (res.ok) {
        const data = await res.json();
        languageCatalog = data.languages || [];
        languageCatalogLoaded = true;
      }
    } catch {
      languageCatalog = [{ code: "en-GB", name: "English", native: "English", rtl: false, quick: true }];
      languageCatalogLoaded = true;
    }
  }

  function selectLanguage(code, rtl = false) {
    saveLocale(code);
    applyRtl(Boolean(rtl));
    showLanguageScreen(false);
    subtitleEl.textContent = ui("subtitle");
    if (history.length === 0 && !welcomeShown) {
      showWelcome();
    }
  }

  function setOpen(open) {
    if (closingTimer) {
      clearTimeout(closingTimer);
      closingTimer = null;
    }

    if (open) {
      backdrop.hidden = false;
      panel.hidden = false;
      root.classList.add("druvo-chat-open");
      launcher.setAttribute("aria-expanded", "true");
      document.body.classList.toggle("druvo-chat-mobile-open", isMobileViewport());

      ensureLanguageCatalog().then(() => {
        if (!locale) {
          showLanguageScreen(true);
        } else {
          showLanguageScreen(false);
          const row = languageCatalog.find((item) => item.code === locale);
          applyRtl(Boolean(row && row.rtl));
        }
        if (!welcomeShown && history.length === 0 && locale) {
          showWelcome();
        } else if (history.length) {
          renderHistory();
        }
      });

      requestAnimationFrame(() => input.focus());
      return;
    }

    root.classList.remove("druvo-chat-open");
    launcher.setAttribute("aria-expanded", "false");
    document.body.classList.remove("druvo-chat-mobile-open");
    input.blur();

    closingTimer = setTimeout(() => {
      panel.hidden = true;
      backdrop.hidden = true;
      closingTimer = null;
    }, isMobileViewport() ? CLOSE_ANIM_MS : 0);
  }

  async function showWelcome() {
    welcomeShown = true;
    const loc = locale || "en-GB";
    try {
      const res = await fetch(`/api/chat/status?locale=${encodeURIComponent(loc)}`);
      if (res.ok) {
        const data = await res.json();
        applyRtl(Boolean(data.rtl));
        appendMessage("assistant", data.welcome || ui("fallbackWelcome"));
        return;
      }
    } catch {
      /* fall through */
    }
    appendMessage("assistant", ui("fallbackWelcome"));
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
    typing.textContent = ui("typing");
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
          locale: locale || "",
        }),
      });

      typing.remove();

      if (res.status === 429) {
        appendMessage("assistant", ui("rateLimit"));
        return;
      }

      if (!res.ok) {
        appendMessage("assistant", ui("errorGeneric"));
        return;
      }

      const data = await res.json();
      if (data.locale && !locale) {
        saveLocale(data.locale);
      }
      applyRtl(Boolean(data.rtl));
      const reply = data.reply || ui("errorGeneric");
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
      appendMessage("assistant", ui("errorConnection"));
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
  backdrop.addEventListener("click", () => setOpen(false));

  langBtn.addEventListener("click", () => {
    ensureLanguageCatalog().then(() => showLanguageScreen(true));
  });

  langMoreBtn.addEventListener("click", () => {
    langSearchWrap.hidden = false;
    renderLanguageResults("");
    langSearch.focus();
  });

  langSearch.addEventListener("input", () => {
    renderLanguageResults(langSearch.value);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !panel.hidden) {
      if (!langScreen.hidden) {
        showLanguageScreen(false);
      } else {
        setOpen(false);
      }
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

  subtitleEl.textContent = ui("subtitle");
  sendBtn.textContent = ui("send");
  input.placeholder = ui("placeholder");

  // Closed by default on every page load — open state is never persisted.
  panel.hidden = true;
  backdrop.hidden = true;
  root.classList.remove("druvo-chat-open");
  launcher.setAttribute("aria-expanded", "false");

  MOBILE_MQL.addEventListener("change", () => {
    if (!panel.hidden && !isMobileViewport()) {
      document.body.classList.remove("druvo-chat-mobile-open");
    }
  });

  ensureLanguageCatalog();
}
