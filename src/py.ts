// Talks to the Python worker. `call` queues requests; `latest` drops superseded ones (slider drags fire many).

type Pending = { resolve: (v: any) => void };

const worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
worker.postMessage({ base: new URL(".", document.baseURI).href });
const pending = new Map<number, Pending>();
let nextId = 1;
const statusListeners: ((text: string) => void)[] = [];

worker.onmessage = (ev: MessageEvent) => {
  const msg = ev.data;
  if (msg.type === "status") {
    statusListeners.forEach((f) => f(msg.text));
    return;
  }
  const p = pending.get(msg.id);
  if (p) {
    pending.delete(msg.id);
    p.resolve(JSON.parse(msg.result));
  }
};

export function onStatus(f: (text: string) => void) {
  statusListeners.push(f);
}

export function call<T = any>(fn: string, req: unknown = {}): Promise<T> {
  const id = nextId++;
  return new Promise((resolve) => {
    pending.set(id, { resolve });
    worker.postMessage({ id, fn, req });
  });
}

// One slot per key: while a call runs, a newer request replaces the waiting one (which resolves to null), and
// a result that is already stale when it arrives resolves to null too - unless keepStale: then every result that
// was computed is delivered (in order). A slider drag needs that: a newer value is always on its way by the time
// a build finishes, so dropping stale results showed nothing until the mouse stopped.
type Slot = { running: boolean; next: (() => void) | null; drop: (() => void) | null; seq: number };
const slots = new Map<string, Slot>();

export function latest<T = any>(key: string, fn: string, req: unknown, keepStale = false): Promise<T | null> {
  let slot = slots.get(key);
  if (!slot) {
    slot = { running: false, next: null, drop: null, seq: 0 };
    slots.set(key, slot);
  }
  const s = slot;
  const seq = ++s.seq;
  return new Promise((resolve) => {
    const run = async () => {
      s.running = true;
      const res = await call<T>(fn, req);
      s.running = false;
      const nxt = s.next;
      s.next = null;
      s.drop = null;
      if (nxt) nxt();
      resolve(seq === s.seq || keepStale ? res : null);
    };
    if (s.running) {
      s.drop?.();
      s.next = run;
      s.drop = () => resolve(null);
    } else {
      run();
    }
  });
}
