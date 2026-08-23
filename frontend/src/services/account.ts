export function telegramLinkUrl(botUsername: string, token: string): string {
  const bot = botUsername.trim().replace(/^@/, '');
  if (!/^[A-Za-z0-9_]{5,32}$/.test(bot) || !token) return '';
  return `https://t.me/${bot}?start=link_${encodeURIComponent(token)}`;
}
