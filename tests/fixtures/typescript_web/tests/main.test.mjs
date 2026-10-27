import assert from "node:assert/strict";
import test from "node:test";

test("renders the initial estimate and updates on input", async () => {
  let onInput;
  const input = { value: "3", addEventListener(type, callback) {
    assert.equal(type, "input");
    onInput = callback;
  } };
  const output = { textContent: "" };
  globalThis.document = { querySelector: (selector) => selector === "#tasks" ? input : output };
  try {
    await import("../.build/main.js");
    assert.equal(output.textContent, "90 minutos");
    input.value = "2";
    onInput();
    assert.equal(output.textContent, "60 minutos");
    input.value = "-1";
    onInput();
    assert.match(output.textContent, /entero/);
  } finally {
    delete globalThis.document;
  }
});
