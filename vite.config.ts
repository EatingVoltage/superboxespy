import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";

// Re-zip python/ into public/py.zip whenever a .py file changes, and reload the page.
function pythonBundle(): Plugin {
  const pack = () => execFileSync("python", [resolve(import.meta.dirname, "scripts/pack_python.py")], { stdio: "inherit" });
  return {
    name: "python-bundle",
    buildStart: pack,
    configureServer(server) {
      server.watcher.add(resolve(import.meta.dirname, "python"));
      server.watcher.on("change", (file) => {
        if (file.endsWith(".py")) {
          pack();
          server.ws.send({ type: "full-reload" });
        }
      });
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [pythonBundle()],
  worker: { format: "es" },
  build: { target: "es2022", chunkSizeWarningLimit: 1200 },
  server: { port: 5199, strictPort: true },
});
