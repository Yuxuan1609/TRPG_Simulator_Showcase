/**
 * Asset background carousel system.
 * Fetches assets from /api/assets/list?context=<ctx> and rotates them.
 * Supports both images and videos with configurable interval.
 */
(function() {
  // Config: interval in milliseconds (30s default, easy to change)
  const CONFIG = {
    interval: 30000,        // 30 seconds per asset
    fadeDuration: 1500,     // crossfade duration in ms
    videoMuted: true,       // videos play muted
    videoLoop: true,
    videoAutoplay: true,
  };

  let assets = [];
  let currentIndex = 0;
  let timer = null;
  let isRunning = false;

  // Context detection from page body data attribute or URL
  function detectContext() {
    const bodyCtx = document.body.dataset.assetContext;
    if (bodyCtx) return bodyCtx;
    const path = window.location.pathname;
    if (path === '/' || path.startsWith('/launcher')) return 'launcher';
    if (path === '/game' || path.startsWith('/api/game')) return 'game';
    if (path === '/character' || path.startsWith('/character')) return 'character';
    if (path === '/editor' || path.startsWith('/editor')) return 'editor';
    return 'game';
  }

  // Create background layers
  function initLayers() {
    let container = document.getElementById('asset-bg-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'asset-bg-container';
      container.style.cssText = 'position:fixed;inset:0;z-index:0;overflow:hidden;';
      document.body.insertBefore(container, document.body.firstChild);
    }
    // Ensure content layers are above background
    document.body.style.position = 'relative';
    document.body.style.zIndex = '1';
  }

  function createMediaElement(asset) {
    const el = document.createElement('div');
    el.className = 'asset-bg-item';
    el.style.cssText = 'position:absolute;inset:0;opacity:0;transition:opacity ' + CONFIG.fadeDuration + 'ms ease-in-out;background-size:cover;background-position:center;';

    if (asset.type === 'video') {
      const video = document.createElement('video');
      video.src = asset.url;
      video.muted = CONFIG.videoMuted;
      video.loop = CONFIG.videoLoop;
      video.autoplay = CONFIG.videoAutoplay;
      video.playsInline = true;
      video.style.cssText = 'width:100%;height:100%;object-fit:cover;';
      el.appendChild(video);
    } else {
      el.style.backgroundImage = 'url("' + asset.url + '")';
    }
    return el;
  }

  function showAsset(index) {
    const container = document.getElementById('asset-bg-container');
    if (!container || !assets.length) return;

    const asset = assets[index % assets.length];
    const newItem = createMediaElement(asset);
    container.appendChild(newItem);

    // Trigger reflow
    void newItem.offsetWidth;
    newItem.style.opacity = '1';

    // Remove old items after fade
    const oldItems = container.querySelectorAll('.asset-bg-item');
    oldItems.forEach(function(item, i) {
      if (item !== newItem) {
        item.style.opacity = '0';
        setTimeout(function() {
          if (item.parentNode) item.parentNode.removeChild(item);
        }, CONFIG.fadeDuration);
      }
    });
  }

  function nextAsset() {
    if (!assets.length) return;
    currentIndex = (currentIndex + 1) % assets.length;
    showAsset(currentIndex);
  }

  function startCarousel() {
    if (isRunning) return;
    isRunning = true;
    if (assets.length > 1) {
      timer = setInterval(nextAsset, CONFIG.interval);
    }
  }

  function stopCarousel() {
    isRunning = false;
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
  }

  // Public API
  window.AssetCarousel = {
    config: CONFIG,
    init: function() {
      initLayers();
      const ctx = detectContext();
      fetch('/api/assets/list?context=' + encodeURIComponent(ctx))
        .then(function(r) { return r.json(); })
        .then(function(data) {
          assets = [];
          if (data.images) assets = assets.concat(data.images);
          if (data.videos) assets = assets.concat(data.videos);
          if (assets.length) {
            currentIndex = 0;
            showAsset(0);
            startCarousel();
          }
        })
        .catch(function(e) { console.error('[AssetCarousel] failed to load:', e); });
    },
    destroy: function() {
      stopCarousel();
      const container = document.getElementById('asset-bg-container');
      if (container) container.innerHTML = '';
    },
    setInterval: function(ms) {
      CONFIG.interval = ms;
      if (isRunning) {
        stopCarousel();
        startCarousel();
      }
    },
  };

  // Auto-init on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.AssetCarousel.init);
  } else {
    window.AssetCarousel.init();
  }
})();
