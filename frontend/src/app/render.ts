import { applicationTemplate } from './template';

export function renderShell(): void {
  const root = document.getElementById('app');
  if (!root) throw new Error('Missing #app root');
  root.innerHTML = applicationTemplate();
}
