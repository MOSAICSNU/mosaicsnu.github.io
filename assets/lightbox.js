// Open figure images in an overlay on the same page. Click, Esc, or Back closes it.
(function () {
  var box = document.createElement("div");
  box.className = "lightbox";
  box.hidden = true;
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  var img = document.createElement("img");
  box.appendChild(img);
  document.body.appendChild(box);

  var opener = null;

  function open(link) {
    var thumb = link.querySelector("img");
    img.src = link.getAttribute("href");
    img.alt = thumb ? thumb.alt : "";
    box.setAttribute("aria-label", img.alt);
    box.hidden = false;
    document.documentElement.classList.add("lightbox-open");
    opener = link;
    box.tabIndex = -1;
    box.focus();
    // A history entry lets the browser/phone Back button close the overlay.
    history.pushState({ lightbox: true }, "");
  }

  function hide() {
    if (box.hidden) return;
    box.hidden = true;
    img.removeAttribute("src");
    document.documentElement.classList.remove("lightbox-open");
    if (opener) opener.focus();
    opener = null;
  }

  function close() {
    if (box.hidden) return;
    if (history.state && history.state.lightbox) history.back();
    else hide();
  }

  document.addEventListener("click", function (e) {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var link = e.target.closest && e.target.closest("figure a");
    if (!link || !link.querySelector("img")) return;
    e.preventDefault();
    open(link);
  });
  box.addEventListener("click", close);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") close();
  });
  window.addEventListener("popstate", hide);
})();
