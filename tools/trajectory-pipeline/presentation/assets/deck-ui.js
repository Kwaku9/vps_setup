/* Host UI only: preserve the shared HyperFrames slide and presenter controller. */
(function () {
  const deck = document.querySelector('hyperframes-slideshow');
  const exit = document.getElementById('exit-fullscreen');
  const fullElement = () => document.fullscreenElement || document.webkitFullscreenElement;
  function sync() {
    const active = !!fullElement() || deck.dataset.expanded === 'true';
    exit.hidden = !active;
    deck.toggleAttribute('data-fullscreen-active', active);
    deck.syncFullscreenButton?.();
  }
  async function leave() {
    try {
      if (fullElement()) {
        const fn = document.exitFullscreen || document.webkitExitFullscreen;
        if (fn) await Promise.resolve(fn.call(document));
      }
    } finally {
      delete deck.dataset.expanded;
      sync();
    }
  }
  exit.addEventListener('click', () => { leave().catch(() => sync()); });
  document.addEventListener('fullscreenchange', sync);
  document.addEventListener('webkitfullscreenchange', sync);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && (fullElement() || deck.dataset.expanded === 'true')) leave().catch(() => sync());
  });
  customElements.whenDefined('hyperframes-slideshow').then(() => {
    deck.toggleFullscreen = async function () {
      if (fullElement() || deck.dataset.expanded === 'true') return leave();
      const fn = deck.requestFullscreen || deck.webkitRequestFullscreen;
      if (fn) {
        try { await Promise.resolve(fn.call(deck)); sync(); return; } catch (_) { /* Use in-page expansion when the browser disallows fullscreen. */ }
      }
      deck.dataset.expanded = 'true';
      sync();
    };
    sync();
  });
})();
