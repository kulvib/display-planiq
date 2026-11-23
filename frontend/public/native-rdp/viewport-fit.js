/* 63D-44: Scale the actual SDL3 canvas to the iframe using a uniform scale.
 * Emscripten SDL3 maps browser CSS pointer coordinates back into window space;
 * never stretch X and Y independently and never rewrite the backing bitmap.
 * No network, credentials, session data, or transport access.
 */
(function (root) {
  "use strict";

  function calculateFit(sourceWidth, sourceHeight, viewportWidth, viewportHeight) {
    const sizes = [sourceWidth, sourceHeight, viewportWidth, viewportHeight];
    if (sizes.some((n) => !Number.isFinite(n) || n <= 0 || n > 32768)) return null;
    const scale = Math.min(viewportWidth / sourceWidth, viewportHeight / sourceHeight);
    const width = Math.min(viewportWidth, Math.max(1, Math.floor(sourceWidth * scale)));
    const height = Math.min(viewportHeight, Math.max(1, Math.floor(sourceHeight * scale)));
    return { width, height };
  }

  function install({ canvas, viewport }) {
    if (!canvas || canvas.id !== "canvas" || canvas.tagName !== "CANVAS" ||
        !viewport || viewport.id !== "viewport" || !viewport.contains(canvas)) {
      throw new TypeError("SDL3-viewport er ikke gyldigt");
    }

    let disposed = false;
    let scheduled = false;
    let animationId = null;

    function applyFit() {
      if (disposed) return;
      const result = calculateFit(
        canvas.width, canvas.height, viewport.clientWidth, viewport.clientHeight
      );
      // SDL3 briefly sets a 1x1 framebuffer during initialization. Do not
      // scale this placeholder to fill the page.
      if (!result || canvas.width < 16 || canvas.height < 16) return;
      const width = result.width + "px";
      const height = result.height + "px";
      if (canvas.style.getPropertyValue("--rdp-fit-width") !== width) {
        canvas.style.setProperty("--rdp-fit-width", width);
      }
      if (canvas.style.getPropertyValue("--rdp-fit-height") !== height) {
        canvas.style.setProperty("--rdp-fit-height", height);
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

    // Source resolution changes update width/height attributes. Viewport
    // changes are observed separately, without polling or RDP frame hooks.
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
