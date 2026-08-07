/** DRUVO image fallbacks — swap broken images for branded placeholders. */

const DEFAULT_PRODUCT = "/static/images/placeholder-product.svg";
const DEFAULT_CATEGORY = "/static/images/placeholder-category.svg";

function applyFallback(img) {
  if (img.dataset.fallbackApplied === "1") return;
  img.dataset.fallbackApplied = "1";
  img.src = img.dataset.placeholder || DEFAULT_PRODUCT;
  img.classList.add("is-placeholder");
}

export function initImageFallbacks(root = document) {
  root.querySelectorAll("img.druvo-img, img[data-placeholder]").forEach((img) => {
    img.addEventListener("error", () => applyFallback(img));
    if (img.complete && img.naturalWidth === 0) applyFallback(img);
  });
}

document.addEventListener("DOMContentLoaded", () => initImageFallbacks());
