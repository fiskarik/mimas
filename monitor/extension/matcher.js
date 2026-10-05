// Only exact domains and their DNS subdomains match; lookalike suffixes do not.
export function hostMatchesDomain(url, signature) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:') return false;
    const host = parsed.hostname.toLowerCase().replace(/\.$/, '');
    const domain = String(signature).toLowerCase().trim().replace(/^\*?\./, '').replace(/\.$/, '');
    if (!domain || domain.includes('/') || domain.includes(':') || domain.includes(' ')) return false;
    return host === domain || host.endsWith(`.${domain}`);
  } catch {
    return false;
  }
}

export function observationsForTabs(products, tabs, focusedWindowId) {
  const result = new Map();
  for (const tab of tabs) {
    if (!tab.url) continue;
    for (const product of products) {
      if (!product.id || !Array.isArray(product.domains) ||
          !product.domains.some(domain => hostMatchesDomain(tab.url, domain))) continue;
      const kind = tab.active && tab.windowId === focusedWindowId ? 'active_tab' : 'background_tab';
      result.set(JSON.stringify([product.id, kind]), {product_id: product.id, kind});
    }
  }
  return result;
}

export function transitions(previousKeys, currentMap) {
  const previous = new Set(previousKeys);
  const current = new Set(currentMap.keys());
  const changes = [];
  for (const key of current) {
    if (!previous.has(key)) changes.push({...currentMap.get(key), state: 'detected'});
  }
  for (const key of previous) {
    if (!current.has(key)) {
      const [product_id, kind] = JSON.parse(key);
      changes.push({product_id, kind, state: 'cleared'});
    }
  }
  return changes;
}
