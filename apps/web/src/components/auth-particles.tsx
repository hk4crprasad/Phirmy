"use client";

import { useEffect, useRef } from "react";

type Particle = { x: number; y: number; z: number; phase: number };

/** A small, self-contained canvas scene; the sign-in form never rerenders for motion. */
export default function AuthParticles() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const panel = canvas?.parentElement;
    const context = canvas?.getContext("2d", { alpha: true });
    if (!canvas || !panel || !context) return;

    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const particles: Particle[] = [];
    const paths = Array.from({ length: 12 }, () => new Path2D());
    let colors: string[] = [];
    function updatePalette() {
      const hex = getComputedStyle(document.documentElement)
        .getPropertyValue("--secondary")
        .trim()
        .replace("#", "");
      const rgb = [0, 2, 4].map((offset) =>
        parseInt(hex.slice(offset, offset + 2), 16),
      );
      colors = paths.map(
        (_, index) =>
          `rgba(${rgb.join(",")}, ${0.06 + (index / (paths.length - 1)) * 0.47})`,
      );
      syncAnimation();
    }
    let width = 0;
    let height = 0;
    let frame = 0;
    let lastPaint = 0;
    let elapsed = 0;
    let inView = false;
    let disposed = false;
    let pointerX = 0;
    let pointerY = 0;
    let tiltX = 0;
    let tiltY = 0;

    function makeParticles() {
      if (particles.length) return;
      const count = 8600;
      const goldenAngle = Math.PI * (3 - Math.sqrt(5));
      for (let index = 0; index < count; index++) {
        const y = 1 - (2 * (index + 0.5)) / count;
        const ring = Math.sqrt(1 - y * y);
        const angle = goldenAngle * index;
        particles.push({
          x: Math.cos(angle) * ring,
          y,
          z: Math.sin(angle) * ring,
          phase: Math.sin(index * 127.1) * 0.5 + 0.5,
        });
      }
    }

    function draw(time: number) {
      if (!context || !width || !height) return;
      makeParticles();
      context.clearRect(0, 0, width, height);
      for (let index = 0; index < paths.length; index++) {
        paths[index] = new Path2D();
      }

      const radius = Math.min(width * 0.44, height * 0.34);
      const centerX = width * 0.5;
      const centerY = height * 0.52;
      const rotation = time * 0.085 + 0.45 + tiltX;
      const pitch = -0.15 + Math.sin(time * 0.13) * 0.12 + tiltY;
      const cosY = Math.cos(rotation);
      const sinY = Math.sin(rotation);
      const cosX = Math.cos(pitch);
      const sinX = Math.sin(pitch);

      for (const point of particles) {
        const ripple =
          1 +
          0.15 * Math.sin(point.y * 5.2 + time * 0.48) +
          0.1 * Math.sin(point.x * 5.5 + point.z * 3.5 - time * 0.36) +
          0.055 * Math.cos(point.z * 9 + point.y * 3 + time * 0.3);
        const x = point.x * ripple;
        const y = point.y * ripple;
        const z = point.z * ripple;
        const rotatedX = x * cosY + z * sinY;
        const rotatedZ = z * cosY - x * sinY;
        const rotatedY = y * cosX - rotatedZ * sinX;
        const depth = rotatedZ * cosX + y * sinX;
        const perspective = 3.6 / (3.6 - depth * 0.42);
        const screenX = centerX + rotatedX * radius * perspective;
        const screenY = centerY + rotatedY * radius * 1.14 * perspective;
        const front = Math.max(0, Math.min(1, (depth + 1.25) / 2.5));
        const distance = Math.hypot(rotatedX, rotatedY);
        // Leave a quiet pocket behind the headline without cutting a hole in the cloud.
        const centerFade = 0.4 + 0.6 * Math.min(1, distance / 0.72);
        const intensity = (0.18 + front * 0.82) * centerFade;
        const bucket = Math.min(
          paths.length - 1,
          Math.floor(intensity * paths.length),
        );
        const size = (0.6 + front * 0.42 + point.phase * 0.22) * perspective;
        paths[bucket].rect(screenX, screenY, size, size);
      }

      paths.forEach((path, index) => {
        context.fillStyle = colors[index];
        context.fill(path);
      });
    }

    function canAnimate() {
      return (
        !disposed &&
        inView &&
        width > 0 &&
        height > 0 &&
        !document.hidden &&
        !motion.matches
      );
    }

    function animate(now: number) {
      frame = 0;
      if (!canAnimate()) return;
      // A decorative scene needs only 30fps, including on high refresh-rate displays.
      if (!lastPaint || now - lastPaint >= 1000 / 30) {
        const delta = lastPaint ? Math.min(now - lastPaint, 64) : 0;
        elapsed += delta / 1000;
        lastPaint = now;
        tiltX += (pointerX * 0.12 - tiltX) * 0.055;
        tiltY += (pointerY * 0.08 - tiltY) * 0.055;
        draw(elapsed);
      }
      frame = requestAnimationFrame(animate);
    }

    function syncAnimation() {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      lastPaint = 0;
      if (motion.matches) {
        tiltX = 0;
        tiltY = 0;
      }
      if (inView && width && height && !document.hidden)
        draw(motion.matches ? 0 : elapsed);
      if (canAnimate()) frame = requestAnimationFrame(animate);
    }

    function resize() {
      if (!canvas || !context) return;
      const bounds = panel!.getBoundingClientRect();
      width = bounds.width;
      height = bounds.height;
      const ratio = Math.min(window.devicePixelRatio || 1, 1.75);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      syncAnimation();
    }

    function movePointer(event: PointerEvent) {
      if (motion.matches) return;
      const bounds = panel!.getBoundingClientRect();
      pointerX = ((event.clientX - bounds.left) / bounds.width - 0.5) * 2;
      pointerY = ((event.clientY - bounds.top) / bounds.height - 0.5) * 2;
    }

    function resetPointer() {
      pointerX = 0;
      pointerY = 0;
    }

    const resizeObserver = new ResizeObserver(resize);
    const visibilityObserver = new IntersectionObserver(([entry]) => {
      inView = entry.isIntersecting;
      syncAnimation();
    });
    const themeObserver = new MutationObserver(updatePalette);
    themeObserver.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });
    updatePalette();
    resizeObserver.observe(panel);
    visibilityObserver.observe(panel);
    motion.addEventListener("change", syncAnimation);
    document.addEventListener("visibilitychange", syncAnimation);
    panel.addEventListener("pointermove", movePointer);
    panel.addEventListener("pointerleave", resetPointer);

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      visibilityObserver.disconnect();
      themeObserver.disconnect();
      motion.removeEventListener("change", syncAnimation);
      document.removeEventListener("visibilitychange", syncAnimation);
      panel.removeEventListener("pointermove", movePointer);
      panel.removeEventListener("pointerleave", resetPointer);
    };
  }, []);

  return (
    <canvas ref={canvasRef} className="auth-particles" aria-hidden="true" />
  );
}
