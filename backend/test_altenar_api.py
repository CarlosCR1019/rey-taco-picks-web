import urllib.request, re

# Buscar API URLs en los JS chunks de Altenar
chunks = [
    'https://sb2wsdk-cdn-altenar2.biahosted.net/chunks/constants-Sv6Wm-ud.js',
    'https://sb2wsdk-cdn-altenar2.biahosted.net/chunks/odds-format-CA_dBq4K.js',
    'https://sb2wsdk-cdn-altenar2.biahosted.net/chunks/event-search-Aa1nWK6u.js'
]

for url in chunks:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            text = resp.read().decode('utf-8', errors='ignore')
            apis = re.findall(r'https?://[a-zA-Z0-9\.\-_/]+api[a-zA-Z0-9\.\-_/]*', text)
            print(f'APIs en {url}:', set(apis))
    except Exception as e:
        print(f'Error en {url}:', e)
