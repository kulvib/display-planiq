import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
const source = fs.readFileSync(new URL("../src/pages/clientdetailspage/terminal/ClientTerminalDialog.jsx", import.meta.url), "utf8");
test("both terminal modes show a bounded countdown without silently renewing root grants", () => {
  assert.match(source, /msg.type === "terminal_idle"/);
  assert.match(source, /idleWarning\?\.reason === "idle" && <Button/);
  assert.match(source, /type: "continue_session", session_id: idleWarning.sessionId/);
  assert.match(source, /closedByComponent \|\| reconnectTimer \|\| stoppedRef.current/);
  assert.match(source, /4408, 4410, 4401, 4403, 1008/);
});
