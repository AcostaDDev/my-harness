import { estimateMinutes } from "./estimate.js";

const input = document.querySelector<HTMLInputElement>("#tasks");
const output = document.querySelector<HTMLOutputElement>("#estimate");
if (!input || !output) throw new Error("Faltan los campos de la calculadora.");

function render(): void {
  try {
    output!.textContent = `${estimateMinutes(Number(input!.value))} minutos`;
  } catch (error) {
    output!.textContent = error instanceof Error ? error.message : "Entrada inválida";
  }
}

input.addEventListener("input", render);
render();
