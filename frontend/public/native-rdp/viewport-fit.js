/* 63D-47: Display existing GNOME primary-monitor pixels without inventing
 * resolution. CSS fit may DOWNSCALE but must never upscale a small RDP canvas.
 * Native mode is 1 canvas pixel per CSS pixel; explicit zoom is 25–200%.
 * Only CSS dimensions change; the browser can scroll oversized images.
 * Neither mode modifies the SDL3 backing buffer, GNOME monitor, FreeRDP
 * protocol, RDP transport or credentials.
 */
(function (root) {
  "use strict";

  function validMode(mode, zoom) {
    return mode === "fit" || mode === "native" ||
      (mode === "zoom" && Number.isInteger(zoom) && zoom >= 25 && zoom <= 200);
  }

  function calculateFit(sourceWidth, sourceHeight, viewportWidth, viewportHeight, mode = "fit", zoom = 100) {
    const sizes = [sourceWidth, sourceHeight, viewportWidth, viewportHeight];
    if (sizes.some((n) => !Number.isFinite(n) || n <= 0 || n > 32768)) return null;
    if (!validMode(mode, zoom)) return null;
    if (mode === "native") return { width: sourceWidth, height: sourceHeight };
    // Do not enlarge the framebuffer to hide a resolution mismatch. The
    // result is a presentation-only downscale with unchanged aspect ratio.
    const scale = mode === "zoom"
      ? Math.min(zoom / 100, 32768 / sourceWidth, 32768 / sourceHeight)
      : Math.min(1, viewportWidth / sourceWidth, viewportHeight / sourceHeight);
    return {
      width: Math.max(1, Math.floor(sourceWidth * scale)),
      height: Math.max(1, Math.floor(sourceHeight * scale)),
    };
  }

  function install({ canvas, viewport, mode = "fit", zoom = 100, onResize = () => {} }) {
    if (!canvas || canvas.id !== "canvas" || canvas.tagName !== "CANVAS" ||
        !viewport || viewport.id !== "viewport" || !viewport.contains(canvas) ||
        !validMode(mode, zoom) || typeof onResize !== "function") {
      throw new TypeError("SDL3-viewport er ikke gyldigt");
    }

    let disposed = false;
    let scheduled = false;
    let animationId = null;
    let lastReport = "";

    function applyFit() {
      if (disposed) return;
      const result = calculateFit(
        canvas.width, canvas.height, viewport.clientWidth, viewport.clientHeight, mode, zoom
      );
      // SDL3's temporary 1x1 framebuffer must not be shown as a desktop.
      if (!result || canvas.width < 16 || canvas.height < 16) return;
      const width = result.width + "px";
      const height = result.height + "px";
      if (canvas.style.getPropertyValue("--rdp-fit-width") !== width) {
        canvas.style.setProperty("--rdp-fit-width", width);
      }
      if (canvas.style.getPropertyValue("--rdp-fit-height") !== height) {
        canvas.style.setProperty("--rdp-fit-height", height);
      }
      const report = {
        sourceWidth: canvas.width, sourceHeight: canvas.height,
        displayWidth: result.width, displayHeight: result.height, mode,
      };
      const key = [report.sourceWidth, report.sourceHeight, report.displayWidth,
        report.displayHeight, report.mode].join(":");
      if (key !== lastReport) {
        lastReport = key;
        onResize(report);
      }
    }

    function scheduleFit() {
      if (disposed || scheduled) return;
      scheduled = true;
      animationId = root.requestAnimationFrame(() => {
        scheduled = false;
        animationId = null;
        applyFit();
      });
    }

    const sizeObserver = typeof root.ResizeObserver === "function"
      ? new root.ResizeObserver(scheduleFit) : null;
    const pixelObserver = typeof root.MutationObserver === "function"
      ? new root.MutationObserver(scheduleFit) : null;
    sizeObserver?.observe(viewport);
    pixelObserver?.observe(canvas, {
      attributes: true, attributeFilter: ["width", "height"],
    });
    root.addEventListener?.("resize", scheduleFit);
    scheduleFit();

    return {
      setMode(nextMode, nextZoom = 100) {
        if (!validMode(nextMode, nextZoom)) {
          throw new TypeError("Ugyldig RDP-visningstilstand");
        }
        if (disposed || (mode === nextMode && zoom === nextZoom)) return;
        mode = nextMode;
        zoom = nextZoom;
        scheduleFit();
      },
      dispose() {
        if (disposed) return;
        disposed = true;
        sizeObserver?.disconnect();
        pixelObserver?.disconnect();
        root.removeEventListener?.("resize", scheduleFit);
        if (animationId !== null) root.cancelAnimationFrame?.(animationId);
      },
    };
  }

  root.PlanIQNativeRdpViewport = Object.freeze({ calculateFit, install });
})(window);
