/*! MERSAD-AI DOM insertion guard; DOMPurify 3.4.18 is loaded before this file. */
(function installMersadDomXssGuard() {
  "use strict";

  if (!window.DOMPurify || typeof window.DOMPurify.sanitize !== "function") {
    throw new Error("MERSAD DOM XSS protection is unavailable; refusing to render dynamic HTML.");
  }

  const descriptor = Object.getOwnPropertyDescriptor(Element.prototype, "innerHTML");
  if (!descriptor || typeof descriptor.get !== "function" || typeof descriptor.set !== "function") {
    throw new Error("MERSAD DOM XSS protection cannot secure the innerHTML setter in this browser.");
  }

  const config = Object.freeze({
    USE_PROFILES: Object.freeze({ html: true, svg: true, svgFilters: true }),
    RETURN_TRUSTED_TYPE: false
  });

  let sanitizing = false;
  let policy = null;

  if (window.trustedTypes && typeof window.trustedTypes.createPolicy === "function") {
    try {
      policy = window.trustedTypes.createPolicy("mersad-ui-html", {
        createHTML(value) {
          return window.DOMPurify.sanitize(String(value ?? ""), config);
        }
      });
    } catch (error) {
      // A policy collision or browser restriction is fail-closed: do not fall back to raw HTML.
      throw new Error("MERSAD Trusted Types policy initialization failed.");
    }
  }

  Object.defineProperty(Element.prototype, "innerHTML", {
    configurable: descriptor.configurable,
    enumerable: descriptor.enumerable,
    get: descriptor.get,
    set(value) {
      if (sanitizing) {
        descriptor.set.call(this, value);
        return;
      }

      sanitizing = true;
      try {
        const source = String(value ?? "");
        const safeValue = policy
          ? policy.createHTML(source)
          : window.DOMPurify.sanitize(source, config);
        descriptor.set.call(this, safeValue);
      } finally {
        sanitizing = false;
      }
    }
  });

  window.MERSAD_DOM_XSS_GUARD = Object.freeze({
    sanitizer: "DOMPurify",
    version: window.DOMPurify.version || "unknown",
    trustedTypes: Boolean(policy)
  });
})();
