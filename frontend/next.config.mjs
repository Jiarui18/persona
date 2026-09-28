import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL(".", import.meta.url));
export default { turbopack: { root }, outputFileTracingRoot: root, devIndicators: false, allowedDevOrigins: ["127.0.0.1"] };
