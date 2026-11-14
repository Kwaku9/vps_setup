/* Slide tracker for reveal.js decks (mentoring history). Injected by
   decks-nginx; deck files are untouched. Reports which slide is on screen
   once it has stayed there 1.5 s, as GET /__t?d=<deck>&i=<index>&n=<total>.
   Sends nothing else: no text, no timing, no cookies of its own. */
(function () {
  var deck = (location.pathname.split("/").pop() || "index").replace(/\.html?$/, "");
  var last = -1, timer = null;
  function slides() {
    var out = [];
    document.querySelectorAll(".reveal .slides > section").forEach(function (h) {
      var v = h.querySelectorAll(":scope > section");
      if (v.length) v.forEach(function (x) { out.push(x); }); else out.push(h);
    });
    return out;
  }
  function send() {
    var all = slides(), i = -1;
    for (var k = 0; k < all.length; k++) if (all[k].classList.contains("present")) { i = k; break; }
    if (i < 0 || i === last) return;
    last = i;
    try {
      fetch("/__t?d=" + encodeURIComponent(deck) + "&i=" + i + "&n=" + all.length,
            { credentials: "same-origin", cache: "no-store", keepalive: true }).catch(function () {});
    } catch (e) { /* never break the deck */ }
  }
  function settle() { clearTimeout(timer); timer = setTimeout(send, 1500); }
  function start() {
    var root = document.querySelector(".reveal .slides");
    if (!root) return; /* not a reveal.js deck: page views are enough */
    new MutationObserver(settle).observe(root, { subtree: true, attributes: true, attributeFilter: ["class"] });
    settle();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
})();
