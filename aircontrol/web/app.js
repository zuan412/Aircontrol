// Aircontrol Client Engine: WebCodecs Hardware HEVC Decoder & Apple CoreDevice Input Bridge

(function() {
  'use strict';

  const canvas = document.getElementById('screen-canvas');
  const ctx = canvas.getContext('2d', { alpha: false, desynchronized: true });
  const standbyOverlay = document.getElementById('standby-overlay');
  const hud = document.getElementById('telemetry-hud');
  const hudFps = document.getElementById('hud-fps');
  const hudCodec = document.getElementById('hud-codec');
  const hudRes = document.getElementById('hud-res');
  const homeIndicator = document.getElementById('home-indicator-wrap');

  let decoder = null;
  let decoderConfig = null;
  let isPointerDown = false;
  let frameCount = 0;
  let lastFpsUpdate = performance.now();
  let lastMoveTime = 0;
  let lastFrameTime = performance.now();

  // --- 1. Fetch Codec & hvcC Configuration from Server ---
  async function fetchCodecConfig() {
    let attempts = 0;
    while (true) {
      attempts++;
      try {
        const resp = await fetch('/codec', { cache: 'no-store' });
        if (resp.ok) {
          const info = await resp.json();
          if (info.codec && info.description) {
            const descBytes = Uint8Array.from(atob(info.description), c => c.charCodeAt(0));
            return {
              codec: info.codec.trim(),
              description: descBytes,
              optimizeForLatency: true,
              hardwareAcceleration: 'prefer-hardware'
            };
          }
        }
      } catch (err) {
        // Stream server is booting up, continue retrying
      }
      await new Promise(r => setTimeout(r, Math.min(200 * attempts, 1000)));
    }
  }

  // --- 2. WebCodecs Hardware VideoDecoder ---
  function buildDecoder(cfg) {
    if (!('VideoDecoder' in window)) {
      console.error('WebCodecs VideoDecoder is not supported in this environment');
      return null;
    }

    try {
      const dec = new VideoDecoder({
        output: (frame) => {
          lastFrameTime = performance.now();
          frameCount++;
          const now = performance.now();
          if (now - lastFpsUpdate >= 1000) {
            const fps = Math.round((frameCount * 1000) / (now - lastFpsUpdate));
            if (hudFps) hudFps.textContent = fps.toString();
            frameCount = 0;
            lastFpsUpdate = now;
          }

          // Update canvas display size if frame resolution changes
          if (canvas.width !== frame.displayWidth || canvas.height !== frame.displayHeight) {
            canvas.width = frame.displayWidth;
            canvas.height = frame.displayHeight;
            if (hudRes) hudRes.textContent = `${frame.displayWidth}x${frame.displayHeight}`;
          }

          // Direct3D 11 hardware-accelerated draw
          ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
          frame.close();

          // Dismiss standby overlay on first frame
          if (standbyOverlay && standbyOverlay.classList.contains('active')) {
            standbyOverlay.classList.remove('active');
          }
        },
        error: (err) => {
          console.warn('WebCodecs Decoder error:', err);
          rebuildDecoder();
        }
      });

      dec.configure(cfg);
      if (hudCodec) hudCodec.textContent = cfg.codec;
      return dec;
    } catch (e) {
      console.error('Failed to configure VideoDecoder:', e);
      return null;
    }
  }

  function rebuildDecoder() {
    if (decoder) {
      try { decoder.close(); } catch (_) {}
      decoder = null;
    }
    if (decoderConfig) {
      decoder = buildDecoder(decoderConfig);
    }
  }

  // --- 3. Stream Ingestion (/stream.bin Chunked Protocol) ---
  async function connectStream() {
    while (true) {
      try {
        // Fetch codec parameters first
        decoderConfig = await fetchCodecConfig();
        decoder = buildDecoder(decoderConfig);

        const response = await fetch('/stream.bin', { cache: 'no-store' });
        if (!response.ok || !response.body) {
          await new Promise(r => setTimeout(r, 1000));
          continue;
        }

        const reader = response.body.getReader();
        let buffer = new Uint8Array(0);

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const merged = new Uint8Array(buffer.length + value.length);
          merged.set(buffer);
          merged.set(value, buffer.length);
          buffer = merged;

          // Parse [4-byte BE len] [1-byte type: 0=key, 1=delta, 2=reset] [payload]
          while (buffer.length >= 4) {
            const frameLen = (buffer[0] << 24) | (buffer[1] << 16) | (buffer[2] << 8) | buffer[3];
            if (buffer.length < 4 + frameLen) break;

            const type = buffer[4]; // 0=key, 1=delta, 2=reset key
            const data = buffer.slice(5, 4 + frameLen);
            buffer = buffer.subarray(4 + frameLen);

            if (type === 2) {
              rebuildDecoder();
            }

            if (decoder && decoder.state === 'configured') {
              try {
                decoder.decode(new EncodedVideoChunk({
                  type: (type === 0 || type === 2) ? 'key' : 'delta',
                  timestamp: performance.now() * 1000,
                  data: data
                }));
              } catch (decErr) {
                console.warn('Decode chunk dropped:', decErr);
              }
            }
          }
        }
      } catch (err) {
        console.debug('Stream reconnecting:', err);
        if (standbyOverlay && !standbyOverlay.classList.contains('active')) {
          standbyOverlay.classList.add('active');
        }
        await new Promise(r => setTimeout(r, 1000));
      }
    }
  }

  // Auto-recovery watchdog: if no frame received for 4s while connected, request PLI keyframe
  setInterval(() => {
    if (decoder && performance.now() - lastFrameTime > 4000) {
      fetch('/pli', { method: 'POST', cache: 'no-store' }).catch(() => {});
    }
  }, 2000);

  // --- 4. Touch & Pointer Coordinate Translation (0..65535 space) ---
  function getNormalizedCoords(e) {
    const rect = canvas.getBoundingClientRect();
    const nx = Math.max(0.0, Math.min(1.0, (e.clientX - rect.left) / rect.width));
    const ny = Math.max(0.0, Math.min(1.0, (e.clientY - rect.top) / rect.height));
    return {
      x: Math.round(nx * 65535),
      y: Math.round(ny * 65535)
    };
  }

  async function sendTouch(type, x, y) {
    try {
      await fetch('/touch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type, x, y })
      });
    } catch (_) {}
  }

  async function sendButton(buttonName) {
    try {
      await fetch('/button', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ button: buttonName, state: 'press' })
      });
    } catch (_) {}
  }

  // Pointer interactions on canvas
  canvas.addEventListener('pointerdown', (e) => {
    isPointerDown = true;
    canvas.setPointerCapture(e.pointerId);
    const { x, y } = getNormalizedCoords(e);
    sendTouch('contact', x, y);
  });

  canvas.addEventListener('pointermove', (e) => {
    if (!isPointerDown) return;
    const now = performance.now();
    if (now - lastMoveTime < 14) return; // Cap pointermove to ~70Hz to avoid queue saturation
    lastMoveTime = now;
    const { x, y } = getNormalizedCoords(e);
    sendTouch('contact', x, y);
  });

  const endTouch = (e) => {
    if (!isPointerDown) return;
    isPointerDown = false;
    try { canvas.releasePointerCapture(e.pointerId); } catch (_) {}
    const { x, y } = getNormalizedCoords(e);
    sendTouch('release', x, y);
  };

  canvas.addEventListener('pointerup', endTouch);
  canvas.addEventListener('pointercancel', endTouch);

  // Mouse wheel scroll to smooth swipe conversion
  let lastWheelTime = 0;
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const now = performance.now();
    if (now - lastWheelTime < 100) return;
    lastWheelTime = now;

    const { x, y } = getNormalizedCoords(e);
    const scrollUp = e.deltaY < 0;
    const startY = scrollUp ? 20000 : 45000;
    const midY = 32768;
    const endY = scrollUp ? 45000 : 20000;

    sendTouch('contact', x, startY);
    setTimeout(() => sendTouch('contact', x, midY), 30);
    setTimeout(() => sendTouch('contact', x, endY), 60);
    setTimeout(() => sendTouch('release', x, endY), 90);
  }, { passive: false });

  // Physical Side Buttons
  document.querySelectorAll('.hw-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const buttonName = btn.getAttribute('data-button');
      if (buttonName) sendButton(buttonName);
    });
  });

  // Home Bar Indicator
  if (homeIndicator) {
    homeIndicator.addEventListener('click', (e) => {
      e.stopPropagation();
      sendButton('home');
    });
  }

  // Keyboard Shortcuts (Home, Lock, HUD)
  window.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey) {
      if (e.key === 'h' || e.key === 'H') {
        e.preventDefault();
        sendButton('home');
      } else if (e.key === 'l' || e.key === 'L') {
        e.preventDefault();
        sendButton('lock');
      } else if (e.key === 'i' || e.key === 'I') {
        e.preventDefault();
        if (hud) hud.classList.toggle('hidden');
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        sendButton('volume-up');
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        sendButton('volume-down');
      }
    }
  });

  // Launch stream engine
  connectStream();
})();
