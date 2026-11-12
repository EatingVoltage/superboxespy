// The app's few shared controls (.grill/ui-toolbars-menus.md): one dropdown for every ▾ (File, Hole), the ? cards
// that hold each view's keys, and the toolbar's buttons. ▾ opens a menu of words; a panel opens only for things
// that need to be seen (the box-type gallery, the logo library).

import { h } from "./params";

/** How far (screen px) the pointer goes before a press becomes a drag: a click's wobble, a double-click's too,
 *  moves nothing. */
export const DRAG_PX = 4;

export type MenuItem =
  | { label: string; run: () => void; detail?: string; title?: string; disabled?: boolean }
  | { heading: string }
  | { note: string }
  | { sep: true };

let current: { anchor: HTMLElement; close: (refocus?: boolean) => void } | null = null;

/** Close whatever menu or card is open. */
export function closeMenu() {
  current?.close();
}

/** The one popover (#menu) under `anchor`: a second click on the same anchor closes it. Esc closes, a click
 *  outside closes. Returns null when this call closed it. */
function popover(anchor: HTMLElement, cls: string, kids: Node[]): HTMLElement | null {
  if (current?.anchor === anchor) {
    current.close();
    return null;
  }
  current?.close();
  const m = document.getElementById("menu")!;
  m.className = cls;
  m.replaceChildren(...kids);
  m.tabIndex = -1;
  m.hidden = false;
  m.style.left = "0px";
  m.style.top = "0px";
  const r = anchor.getBoundingClientRect();
  const w = m.offsetWidth;
  m.style.left = `${r.left + w > innerWidth - 8 ? Math.max(8, r.right - w) : r.left}px`;
  m.style.top = `${r.bottom + 4}px`;
  m.style.maxHeight = `${Math.max(160, innerHeight - r.bottom - 16)}px`;
  anchor.setAttribute("aria-expanded", "true");
  const outside = (e: PointerEvent) => {
    const t = e.target as Node;
    if (!m.contains(t) && !anchor.contains(t)) close();
  };
  const items = () => [...m.querySelectorAll<HTMLButtonElement>("button:not(:disabled)")];
  m.onkeydown = (e) => {
    const list = items();
    const i = list.indexOf(document.activeElement as HTMLButtonElement);
    const go = (j: number) => list[(j + list.length) % list.length]?.focus();
    if (e.key === "Escape") close(true);
    else if (e.key === "ArrowDown") go(i + 1);
    else if (e.key === "ArrowUp") go(i < 0 ? -1 : i - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(-1);
    else if (e.key === "Tab") close();
    else return;
    if (e.key !== "Tab") e.preventDefault();
    e.stopPropagation();
  };
  function close(refocus = false) {
    if (current?.anchor !== anchor) return;
    current = null;
    m.hidden = true;
    m.onkeydown = null;
    anchor.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", outside, true);
    window.removeEventListener("resize", onResize);
    if (refocus) anchor.focus({ preventScroll: true });
  }
  const onResize = () => close();
  document.addEventListener("pointerdown", outside, true);
  window.addEventListener("resize", onResize);
  current = { anchor, close };
  m.focus({ preventScroll: true });
  return m;
}

/** A dropdown of words under `anchor`. Arrow keys move, Enter picks, Esc closes. */
export function menu(anchor: HTMLElement, items: MenuItem[], empty = "Nothing here yet") {
  const kids: Node[] = [];
  if (!items.length) kids.push(h("div", { class: "menu-note" }, empty));
  for (const it of items) {
    if ("sep" in it) kids.push(h("div", { class: "menu-sep", role: "separator" }));
    else if ("heading" in it) kids.push(h("div", { class: "menu-head" }, it.heading));
    else if ("note" in it) kids.push(h("div", { class: "menu-note" }, it.note));
    else {
      const b = h("button", { type: "button", role: "menuitem", title: it.title ?? "", disabled: !!it.disabled },
        h("span", { class: "menu-label" }, it.label), it.detail ? h("span", { class: "menu-detail" }, it.detail) : "");
      b.onclick = () => {
        current?.close();
        it.run();
      };
      kids.push(b);
    }
  }
  const m = popover(anchor, "menu", kids);
  m?.setAttribute("role", "menu");
}

/** A ? card: the view's keys, then what its lines and colours mean. */
export function helpCard(anchor: HTMLElement, title: string, keys: [string, string][], notes: string[] = []) {
  const dl = h("dl", { class: "help-keys" });
  for (const [k, what] of keys) dl.append(h("dt", {}, ...k.split(" / ").flatMap((x, i) => [i ? " / " : "", h("kbd", {}, x)])),
    h("dd", {}, what));
  const m = popover(anchor, "menu help", [h("div", { class: "help-title" }, title), dl,
    ...notes.map((n) => h("p", { class: "help-note" }, n))]);
  m?.setAttribute("role", "dialog");
  m?.setAttribute("aria-label", title);
}

/** A toolbar or bar button. */
export function btn(label: string, title: string, run: (b: HTMLButtonElement) => void, cls = ""): HTMLButtonElement {
  const b = h("button", { type: "button", title, class: cls }, label) as HTMLButtonElement;
  b.onclick = () => run(b);
  return b;
}

/** A button that opens a menu (its label ends in ▾). */
export function menuButton(label: string, title: string, items: () => MenuItem[] | Promise<MenuItem[]>, empty?: string) {
  const b = h("button", { type: "button", title, "aria-haspopup": "menu", "aria-expanded": "false" }, `${label} ▾`) as HTMLButtonElement;
  b.onclick = async () => menu(b, await items(), empty);
  return b;
}

/** The ? at a toolbar's end (the ? key opens it too). */
export function helpButton(open: (b: HTMLButtonElement) => void): HTMLButtonElement {
  const b = h("button", { type: "button", class: "help-btn", title: "Keys, and what the lines and colours mean (?)",
    "aria-label": "Help", "aria-haspopup": "dialog", "aria-expanded": "false" }, "?") as HTMLButtonElement;
  b.onclick = () => open(b);
  return b;
}

/** Pick one of 2-4: a segmented control. */
export function seg<T extends string | number>(label: string, options: [T, string, string?][], value: T, pick: (v: T) => void) {
  const el = h("span", { class: "seg", role: "group", "aria-label": label });
  for (const [v, text, title] of options) {
    const b = h("button", { type: "button", "aria-pressed": String(v === value), title: title ?? "" }, text);
    b.onclick = () => v !== value && pick(v);
    el.append(b);
  }
  return el;
}

/** An on/off for how something looks (Dimensions, Bold): a button lit while on. */
export function toggle(label: string, title: string, on: boolean, set: (on: boolean) => void): HTMLButtonElement {
  const b = h("button", { type: "button", class: "toggle", title, "aria-pressed": String(on) }, label) as HTMLButtonElement;
  b.onclick = () => {
    const next = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", String(next));
    set(next);
  };
  return b;
}

/** A field the user types into. */
const typing = (t: Element | null): t is HTMLElement =>
  t instanceof HTMLElement && t.matches("textarea, select, input:not([type=checkbox], [type=radio], [type=range])");

/** Fill a bar with the selection's settings. While the user is in one of its fields and the bar still shows the same
 *  thing (`key`: what's selected), that field stays - what's typed in it, its caret - and only what's around it is
 *  drawn anew. A build landing then neither pulls the field from under the user (the keys meant for it would reach
 *  the editor: Backspace deletes the item) nor holds back what the bar says about the build. The field is found in
 *  the new drawing by its aria-label and takes that one's handlers, so they act on the selection as it is now. */
export function fillBar(bar: HTMLElement, key: string, kids: (Node | string)[]) {
  const field = document.activeElement;
  const same = bar.dataset.key === key;
  bar.dataset.key = key;
  const nodes = kids.map((k) => (typeof k === "string" ? document.createTextNode(k) : k));
  const label = field?.getAttribute("aria-label");
  const top = same && typing(field) && label ? [...bar.children].find((c) => c.contains(field)) : undefined;
  const sel = `[aria-label="${CSS.escape(label ?? "")}"]`;
  const twinTop = top && nodes.find((n) => n instanceof Element && (n.matches(sel) || n.querySelector(sel)));
  const twin = twinTop instanceof Element ? (twinTop.matches(sel) ? twinTop : twinTop.querySelector(sel)) : null;
  if (!top || !twin || twin.tagName !== field!.tagName) {
    bar.replaceChildren(...nodes);
    return;
  }
  for (const n of [...bar.childNodes]) if (n !== top) n.remove();
  const i = nodes.indexOf(twinTop!);
  top.before(...nodes.slice(0, i));
  top.after(...nodes.slice(i + 1));
  if (top !== field) top.className = (twinTop as Element).className;     // its holder's look (a missing value's red)
  const f = field as HTMLElement, t = twin as HTMLElement;
  f.onchange = t.onchange;
  f.oninput = t.oninput;
  f.onkeydown = t.onkeydown;
  f.onfocus = t.onfocus;
}

/** A toolbar: its kids, a spacer, then what goes at the right end. */
export function fillToolbar(el: HTMLElement, left: (Node | string)[], right: (Node | string)[] = []) {
  el.replaceChildren(...left, h("div", { class: "spacer" }), ...right);
}
