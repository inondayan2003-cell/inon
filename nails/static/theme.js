// Applies the look chosen in Settings (light or dark) before the page draws.
// The phone's own dark mode setting is ignored on purpose.
(function () {
  var look = "light";
  try { look = JSON.parse(localStorage.getItem("nails.look")) === "dark" ? "dark" : "light"; } catch (e) { /* private mode */ }
  document.documentElement.setAttribute("data-look", look);
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta && look === "dark") meta.setAttribute("content", "#1d1117");
})();
