/** Return to the independent EASPhub workbench while retaining presentation preferences. */
export function easphubPlatformUrl(mode: 'light' | 'dark'): string | undefined {
  const configured = import.meta.env.VITE_EASPHUB_PLATFORM_URL;
  if (typeof configured !== 'string' || !configured.trim()) return undefined;
  let url: URL;
  try {
    url = new URL(configured.trim(), window.location.href);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('Invalid platform URL');
  } catch { return undefined; }
  const requestedDensity = new URLSearchParams(window.location.search).get('density');
  const density = document.documentElement.dataset.eaDensity || requestedDensity || '1';
  url.searchParams.set('mode', mode);
  url.searchParams.set('density', ['0', '1', '2'].includes(density) ? density : '1');
  return url.href;
}
