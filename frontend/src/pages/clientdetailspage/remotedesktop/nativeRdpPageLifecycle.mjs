/** Document lifetime is distinct from visibility. Never disconnect on tab switch. */
export function installNativeRdpPageLifecycle(target, { leave, restore }) {
  let departed = false;
  const onPageHide = () => {
    if (departed) return;
    departed = true;
    leave();
  };
  const onPageShow = (event) => {
    if (!departed || !event.persisted) return;
    departed = false;
    restore();
  };
  target.addEventListener("pagehide", onPageHide);
  target.addEventListener("pageshow", onPageShow);
  return () => {
    target.removeEventListener("pagehide", onPageHide);
    target.removeEventListener("pageshow", onPageShow);
  };
}
