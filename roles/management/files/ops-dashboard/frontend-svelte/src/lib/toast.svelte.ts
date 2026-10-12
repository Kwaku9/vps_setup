export const toasts = $state<{ id: number; text: string; bad: boolean }[]>([]);
let n = 0;
export function toast(text: string, bad = false) {
  const id = ++n;
  toasts.push({ id, text, bad });
  setTimeout(() => { const i = toasts.findIndex((t) => t.id === id); if (i >= 0) toasts.splice(i, 1); }, bad ? 6000 : 3500);
}
