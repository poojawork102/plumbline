import "@testing-library/jest-dom/vitest";

// jsdom has no PointerEvent; without this, fireEvent.pointer* drops clientX/Y.
if (typeof window !== "undefined" && !window.PointerEvent) {
  class PointerEvent extends MouseEvent {
    constructor(type, init = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
    }
  }
  window.PointerEvent = PointerEvent;
}
