// Advertising pixels (Meta, TikTok, Snapchat, Google Analytics 4) — loaded ONLY after the visitor
// accepts marketing cookies (UK GDPR / PECR). Nothing loads when no pixel ID is configured.
// Shop events: page view, product view, add to basket, start checkout, purchase.

const cfgEl = document.getElementById("druvo-marketing-config");
const cfg = cfgEl ? JSON.parse(cfgEl.textContent) : {};
const enabled = Boolean(cfg.meta || cfg.tiktok || cfg.snap || cfg.ga4);
const KEY = "druvo_consent_v1";

function readConsent() {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

function writeConsent(value) {
  try { localStorage.setItem(KEY, value); } catch { /* private mode: ask again next visit */ }
}

function loadScript(src) {
  const s = document.createElement("script");
  s.async = true;
  s.src = src;
  document.head.appendChild(s);
}

let loaded = false;
const queue = [];

function loadPixels() {
  if (loaded) return;
  loaded = true;
  if (cfg.meta) {
    /* Meta Pixel base code */
    !function (f, b, e, v, n, t, s) {
      if (f.fbq) return; n = f.fbq = function () { n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments); };
      if (!f._fbq) f._fbq = n; n.push = n; n.loaded = !0; n.version = "2.0"; n.queue = [];
    }(window, document);
    loadScript("https://connect.facebook.net/en_US/fbevents.js");
    window.fbq("init", cfg.meta);
  }
  if (cfg.tiktok) {
    /* TikTok Pixel base code (official loader) */
    const w = window, t = "ttq";
    w.TiktokAnalyticsObject = t;
    const ttq = (w[t] = w[t] || []);
    ttq.methods = ["page", "track", "identify", "instances", "debug", "on", "off", "once", "ready", "alias",
      "group", "enableCookie", "disableCookie", "holdConsent", "revokeConsent", "grantConsent"];
    ttq.setAndDefer = (obj, m) => { obj[m] = function () { obj.push([m].concat(Array.prototype.slice.call(arguments, 0))); }; };
    ttq.methods.forEach((m) => ttq.setAndDefer(ttq, m));
    ttq.instance = (id) => { const e = ttq._i[id] || []; ttq.methods.forEach((m) => ttq.setAndDefer(e, m)); return e; };
    ttq.load = (id, opts) => {
      const r = "https://analytics.tiktok.com/i18n/pixel/events.js";
      ttq._i = ttq._i || {}; ttq._i[id] = []; ttq._i[id]._u = r;
      ttq._t = ttq._t || {}; ttq._t[id] = +new Date();
      ttq._o = ttq._o || {}; ttq._o[id] = opts || {};
      loadScript(`${r}?sdkid=${encodeURIComponent(id)}&lib=${t}`);
    };
    ttq.load(cfg.tiktok);
  }
  if (cfg.snap) {
    /* Snap Pixel base code */
    const snaptr = (window.snaptr = function () { snaptr.handleRequest ? snaptr.handleRequest.apply(snaptr, arguments) : snaptr.queue.push(arguments); });
    snaptr.queue = [];
    loadScript("https://sc-static.net/scevent.min.js");
    window.snaptr("init", cfg.snap, {});
  }
  if (cfg.ga4) {
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag("js", new Date());
    window.gtag("config", cfg.ga4);
    loadScript(`https://www.googletagmanager.com/gtag/js?id=${encodeURIComponent(cfg.ga4)}`);
  }
  track("PageView");
  queue.splice(0).forEach(([name, data]) => track(name, data));
}

// One shop event, translated for each platform.
export function track(name, data = {}) {
  if (!enabled) return;
  if (!loaded) { queue.push([name, data]); return; }
  const value = Number(data.value || 0);
  const ids = data.content_ids || [];
  const common = { value, currency: "GBP", content_ids: ids, content_type: "product" };
  const map = {
    PageView: { meta: "PageView", tiktok: null, snap: "PAGE_VIEW", ga4: null },
    ViewContent: { meta: "ViewContent", tiktok: "ViewContent", snap: "VIEW_CONTENT", ga4: "view_item" },
    AddToCart: { meta: "AddToCart", tiktok: "AddToCart", snap: "ADD_CART", ga4: "add_to_cart" },
    InitiateCheckout: { meta: "InitiateCheckout", tiktok: "InitiateCheckout", snap: "START_CHECKOUT", ga4: "begin_checkout" },
    Purchase: { meta: "Purchase", tiktok: "CompletePayment", snap: "PURCHASE", ga4: "purchase" },
  }[name];
  if (!map) return;
  if (cfg.meta && window.fbq) window.fbq("track", map.meta, name === "PageView" ? undefined : common);
  if (cfg.tiktok && window.ttq) {
    if (name === "PageView") window.ttq.page();
    else window.ttq.track(map.tiktok, { value, currency: "GBP", contents: ids.map((id) => ({ content_id: id, content_type: "product" })) });
  }
  if (cfg.snap && window.snaptr) {
    window.snaptr("track", map.snap, name === "PageView" ? {} : { price: value, currency: "GBP", item_ids: ids });
  }
  if (cfg.ga4 && window.gtag && map.ga4) {
    window.gtag("event", map.ga4, { value, currency: "GBP", items: ids.map((id) => ({ item_id: id })) });
  }
}

function showBanner() {
  const banner = document.getElementById("consent-banner");
  if (!banner) return;
  banner.hidden = false;
  banner.querySelector("[data-consent-accept]")?.addEventListener("click", () => {
    writeConsent("accepted"); banner.hidden = true; loadPixels();
  });
  banner.querySelector("[data-consent-reject]")?.addEventListener("click", () => {
    writeConsent("rejected"); banner.hidden = true;
  });
}

function init() {
  if (!enabled) return;
  // "Cookie settings" link in the footer lets visitors change their mind.
  document.querySelectorAll("[data-consent-reopen]").forEach((el) => el.addEventListener("click", (e) => {
    e.preventDefault();
    try { localStorage.removeItem(KEY); } catch { /* ignore */ }
    location.reload();
  }));
  const consent = readConsent();
  if (consent === "accepted") loadPixels();
  else if (consent !== "rejected") showBanner();

  const product = document.querySelector("[data-product-page]");
  if (product) {
    // Same ids as the product feed (variant SKU), so ads can match catalogue items.
    let variants = [];
    try { variants = JSON.parse(product.dataset.variants || "[]"); } catch { /* ignore */ }
    const ids = variants.map((v) => v.sku).filter(Boolean);
    const price = variants.length ? Number(variants[0].price_gbp || 0) : 0;
    track("ViewContent", { value: price, content_ids: ids.length ? ids : [product.dataset.slug] });
  }
  if (location.pathname === "/checkout") {
    track("InitiateCheckout", {});
  }
}

window.addEventListener("druvo:add_to_cart", (e) => {
  const item = e.detail || {};
  track("AddToCart", { value: Number(item.price_gbp || 0) * Number(item.quantity || 1), content_ids: [item.sku || item.slug] });
});
window.addEventListener("druvo:purchase", (e) => {
  const d = e.detail || {};
  track("Purchase", { value: Number(d.value || 0), content_ids: d.content_ids || [] });
});

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
else init();
