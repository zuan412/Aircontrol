// Aircontrol Client Engine: WebCodecs Hardware HEVC Decoder & Input Bridge

(function() {
  'use strict';

  const canvas = document.getElementById('screen-canvas');
  const ctx = canvas.getContext('2d', { alpha: false, desynchronized: true });
  const standbyOverlay = document.getElementById('standby-overlay');
  const hud = document.getElementById('telemetry-hud');
  const hudFps = document.getElementById('hud-fps');
  const hudRes = document.getElementById('hud-res');
  const homeIndicator = document.getElementById('home-indicator-wrap');

  let decoder = null;
  let isDecoderConfigured = false;
  let isPointerDown = false;
  let frameCount = 0;
  let lastFpsUpdate = performance.now();
  let lastMoveTime = 0;

  // --- 1. WebCodecs Hardware Decoder ---
  function initDecoder() {
    if (!('VideoDecoder' in window)) {
      console.error('WebCodecs VideoDecoder is not supported in this browser environment');
      return;
    }

    decoder = new VideoDecoder({
      output: (frame) => {
        frameCount++;
        const now = performance.now();
        if (now - lastFpsUpdate >= 1000) {
          const fps = Math.round((frameCount * 1000) / (now - lastFpsUpdate));
          if (hudFps) hudFps.textContent = fps.toString();
          frameCount = 0;
          lastFpsUpdate = now;
        }

        if (canvas.width !== frame.displayWidth || canvas.height !== frame.displayHeight) {
          canvas.width = frame.displayWidth;
          canvas.height = frame.displayHeight;
          if (hudRes) hudRes.textContent = `${frame.displayWidth}x${frame.displayHeight}`;
        }

        ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
        frame.close();

        // Dismiss standby overlay on first successful frame
        if (standbyOverlay && standbyOverlay.classList.contains('active')) {
          standbyOverlay.classList.remove('active');
        }
      },
      error: (e) => {
        console.warn('WebCodecs Decoder error, resetting:', e);
        isDecoderConfigured = false;
      }
    });
  }

  // --- 2. Stream Ingestion (Chunked Binary Protocol) ---
  async function connectStream() {
    initDecoder();
    while (true) {
      try {
        const response = await fetch('/stream');
        if (!response.ok || !response.body) {
          await new Promise(r => setTimeout(r, 1500));
          continue;
        }

        const reader = response.body.getReader();
        let buffer = new Uint8Array(0);

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          // Append incoming chunk
          const newBuf = new Uint8Array(buffer.length + value.length);
          newBuf.set(buffer);
          newBuf.set(value, buffer.length);
          buffer = newBuf;

          // Process 4-byte prefixed access units
          while (buffer.length >= 4) {
            const frameLen = (buffer[0] << 24) | (buffer[1] << 16) | (buffer[2] << 8) | buffer[3];
            if (buffer.length < 4 + frameLen) break;

            const frameData = buffer.subarray(4, 4 + frameLen);
            buffer = buffer.subarray(4 + frameLen);

            decodeAccessUnit(frameData);
          }
        }
      } catch (err) {
        console.debug('Stream connection retry:', err);
        if (standbyOverlay && !standbyOverlay.classList.contains('active')) {
          standbyOverlay.classList.add('active');
        }
        await new Promise(r => setTimeout(r, 1000));
      }
    }
  }

  function decodeAccessUnit(data) {
    if (!decoder) return;

    // Check for HEVC keyframe NAL (VPS: 32, SPS: 33, PPS: 34, IDR: 19 or 20)
    let isKey = false;
    if (data.length > 5) {
      const nalType = (data[4] >> 1) & 0x3f;
      if (nalType >= 16 && nalType <= 34) {
        isKey = true;
      }
    }

    if (!isDecoderConfigured || isKey) {
      try {
        decoder.configure({
          codec: 'hev1.1.6.L120.90', // Standard iOS Main HEVC profile
          hardwareAcceleration: 'prefer-hardware',
          optimizeForLatency: true
        });
        isDecoderConfigured = true;
      } catch (e) {
        console.error('Decoder configure failed:', e);
        return;
      }
    }

    try {
      decoder.decode(new EncodedVideoChunk({
        type: isKey ? 'key' : 'delta',
        timestamp: performance.now() * 1000,
        data: data
      }));
    } catch (e) {
      // If decode fails, reconfigure next frame
      isDecoderConfigured = false;
    }
  }

  // --- 3. Input Handling & Pointer Translation ---
  function getNormalizedCoords(e) {
    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    return {
      x: Math.max(0.0, Math.min(1.0, x)),
      y: Math.max(0.0, Math.min(1.0, y))
    };
  }

  async function sendTouch(action, x, y) {
    try {
      await fetch('/touch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, x, y })
      });
    } catch (e) {
      console.debug('Touch send failed:', e);
    }
  }

  async function sendButton(button) {
    try {
      await fetch('/button', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ button })
      });
    } catch (e) {
      console.debug('Button send failed:', e);
    }
  }

  // Pointer events on canvas
  canvas.addEventListener('pointerdown', (e) => {
    isPointerDown = true;
    canvas.setPointerCapture(e.pointerId);
    const { x, y } = getNormalizedCoords(e);
    sendTouch('down', x, y);
  });

  canvas.addEventListener('pointermove', (e) => {
    if (!isPointerDown) return;
    const now = performance.now();
    if (now - lastMoveTime < 14) return; // Limit to ~70Hz to prevent flooding
    lastMoveTime = now;
    const { x, y } = getNormalizedCoords(e);
    sendTouch('move', x, y);
  });

  const endTouch = (e) => {
    if (!isPointerDown) return;
    isPointerDown = false;
    try { canvas.releasePointerCapture(e.pointerId); } catch (_) {}
    const { x, y } = getNormalizedCoords(e);
    sendTouch('up', x, y);
  };

  canvas.addEventListener('pointerup', endTouch);
  canvas.addEventListener('pointercancel', endTouch);

  // Mouse wheel scroll conversion
  let lastWheelTime = 0;
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const now = performance.now();
    if (now - lastWheelTime < 80) return;
    lastWheelTime = now;

    const { x, y } = getNormalizedCoords(e);
    const scrollUp = e.deltaY < 0;
    const startY = scrollUp ? 0.35 : 0.65;
    const endY = scrollUp ? 0.65 : 0.35;

    // Simulate drag swipe
    sendTouch('down', x, startY).then(() => {
      setTimeout(() => sendTouch('move', x, (startY + endY) / 2), 25);
      setTimeout(() => sendTouch('move', x, endY), 50);
      setTimeout(() => sendTouch('up', x, endY), 80);
    });
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

  // Keyboard Shortcuts
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

  // Start stream consumption
  connectStream();
})();
