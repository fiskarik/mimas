'use client';

import {useEffect, useRef} from 'react';

const GAP = 16;
const RADIUS = 150;
const JITTER = 2.6;

function hash2(i: number, j: number) {
  let n = (i * 374761393 + j * 668265263) | 0;
  n = (n ^ (n >> 13)) * 1274126177;
  return ((n ^ (n >> 16)) >>> 0) / 4294967295;
}

/** Section-bound decorative version of the supplied CursorField effect. */
export function CursorDots() {
  const sectionRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const section = sectionRef.current;
    const canvas = canvasRef.current;
    if (!section || !canvas) return;
    const ctx = canvas.getContext('2d', {alpha: true});
    if (!ctx) return;

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
    const pointer = {x: 0, y: 0, active: false};
    let width = 0;
    let height = 0;
    let visible = false;
    let frame = 0;
    const canRespond = () => !reducedMotion.matches && finePointer.matches;

    const paint = () => {
      ctx.clearRect(0, 0, width, height);
      const cols = Math.ceil(width / GAP) + 1;
      const rows = Math.ceil(height / GAP) + 1;
      for (let j = 0; j < rows; j += 1) {
        for (let i = 0; i < cols; i += 1) {
          const n = hash2(i, j);
          const n2 = hash2(j + 17, i + 9);
          let x = i * GAP + (n - 0.5) * JITTER;
          let y = j * GAP + (n2 - 0.5) * JITTER;
          let alpha = 0.14 + n * 0.2;
          let size = 1.05 + n2 * 0.7;
          if (pointer.active && canRespond()) {
            const dx = x - pointer.x;
            const dy = y - pointer.y;
            const distance = Math.hypot(dx, dy);
            if (distance < RADIUS) {
              const falloff = (1 - distance / RADIUS) ** 2;
              const inverseDistance = 1 / (distance || 1);
              x += dx * inverseDistance * falloff * 11;
              y += dy * inverseDistance * falloff * 11;
              alpha += falloff * 0.35;
              size += falloff * 0.75;
            }
          }
          ctx.fillStyle = 'rgba(172, 179, 176, ' + alpha + ')';
          ctx.beginPath();
          ctx.arc(x, y, size * 0.55, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    };

    const requestPaint = () => {
      if (!visible || frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        if (visible) paint();
      });
    };

    const resize = () => {
      width = section.clientWidth;
      height = section.clientHeight;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      requestPaint();
    };

    const onMove = (event: PointerEvent) => {
      if (!canRespond() || event.pointerType === 'touch') return;
      const bounds = section.getBoundingClientRect();
      pointer.x = event.clientX - bounds.left;
      pointer.y = event.clientY - bounds.top;
      pointer.active = true;
      requestPaint();
    };

    const onLeave = () => {
      if (!pointer.active) return;
      pointer.active = false;
      requestPaint();
    };

    const onPreferenceChange = () => {
      pointer.active = false;
      requestPaint();
    };

    const observer = new ResizeObserver(resize);
    observer.observe(section);
    const visibilityObserver = new IntersectionObserver(entries => {
      visible = entries[0]?.isIntersecting ?? false;
      if (visible) requestPaint();
      else pointer.active = false;
    }, {rootMargin: '100px'});
    visibilityObserver.observe(section);
    section.addEventListener('pointermove', onMove, {passive: true});
    section.addEventListener('pointerleave', onLeave);
    reducedMotion.addEventListener('change', onPreferenceChange);
    finePointer.addEventListener('change', onPreferenceChange);

    return () => {
      window.cancelAnimationFrame(frame);
      observer.disconnect();
      visibilityObserver.disconnect();
      section.removeEventListener('pointermove', onMove);
      section.removeEventListener('pointerleave', onLeave);
      reducedMotion.removeEventListener('change', onPreferenceChange);
      finePointer.removeEventListener('change', onPreferenceChange);
    };
  }, []);

  return <div className="cursor-dots" ref={sectionRef} aria-hidden="true">
    <canvas ref={canvasRef}/>
  </div>;
}
