import asyncio
import httpx
from bs4 import BeautifulSoup
import json
from datetime import datetime
import http.server
import socketserver
import threading
import os

# ===================================================================
# 1. ARKA PLAN: ASENKRON TARAYICI (BACKEND)
# ===================================================================
TARGETS = [
    {
        "source": "KOSGEB",
        "url": "https://www.kosgeb.gov.tr/site/tr/genel/liste/2/duyurular",
        "selectors": {
            "container": "div.duyuru-item, div.announcement-item, li.duyuru, div.news-item, article",
            "title": "h2, h3, h4, a, .baslik, .title",
            "link": "a"
        },
        "base_url": "https://www.kosgeb.gov.tr"
    },
    {
        "source": "TÜBİTAK",
        "url": "https://tubitak.gov.tr/tr",
        "selectors": {
            "container": "div.views-row, article, div.news-item, div.card, li.views-row",
            "title": "span.field-content, h2, h3, h4, .node__title, a",
            "link": "a"
        },
        "base_url": "https://tubitak.gov.tr"
    },
    {
        "source": "Sanayi Bakanlığı",
        "url": "https://www.sanayi.gov.tr/haber-duyuru/duyurular",
        "selectors": {
            "container": "div.duyuru-liste-item, div.list-item, article, li.haber-item",
            "title": "h2, h3, h4, .title, a",
            "link": "a"
        },
        "base_url": "https://www.sanayi.gov.tr"
    },
    {
        "source": "Hazine ve Maliye",
        "url": "https://www.hmb.gov.tr/duyurular",
        "selectors": {
            "container": "div.news-item, li.news, article, div.card",
            "title": "h2, h3, h4, a, .title",
            "link": "a"
        },
        "base_url": "https://www.hmb.gov.tr"
    }
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive"
}

def parse_html(html_content, config):
    soup = BeautifulSoup(html_content, 'html.parser')
    extracted_data = []

    # Virgülle ayrılmış birden fazla selector dene
    container_selectors = [s.strip() for s in config['selectors']['container'].split(',')]
    containers = []
    for sel in container_selectors:
        found = soup.select(sel)
        if found:
            containers = found
            print(f"  -> '{sel}' selektörü ile {len(found)} konteyner bulundu.")
            break

    if not containers:
        # Fallback: tüm linkleri tara
        print(f"  -> Konteyner bulunamadı, link fallback kullanılıyor.")
        links = soup.select("a[href]")
        for link in links[:20]:  # İlk 20 link
            text = link.text.strip()
            href = link.get('href', '')
            if len(text) > 10 and not href.startswith('#') and not href.startswith('javascript'):
                if href.startswith('/'):
                    href = config['base_url'] + href
                extracted_data.append({
                    "source": config['source'],
                    "title": text[:200],
                    "url": href,
                    "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
        return extracted_data

    title_selectors = [s.strip() for s in config['selectors']['title'].split(',')]

    for box in containers:
        title_text = "Başlık Bulunamadı"
        for t_sel in title_selectors:
            title_el = box.select_one(t_sel)
            if title_el and title_el.text.strip():
                title_text = title_el.text.strip()[:200]
                break

        link_element = box.select_one("a")
        link_href = link_element['href'] if link_element and link_element.has_attr('href') else ""

        if link_href.startswith('/'):
            link_href = config['base_url'] + link_href
        elif link_href and not link_href.startswith('http'):
            link_href = config['base_url'] + '/' + link_href

        extracted_data.append({
            "source": config['source'],
            "title": title_text,
            "url": link_href,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

    return extracted_data


async def fetch_site(client, config):
    try:
        response = await client.get(
            config['url'],
            headers=HEADERS,
            timeout=20.0,
            follow_redirects=True
        )
        response.raise_for_status()
        data = parse_html(response.text, config)
        print(f"[BAŞARILI] {config['source']}: {len(data)} duyuru bulundu.")
        return data
    except Exception as exc:
        print(f"[HATA] {config['source']} taranamadı: {exc}")
        return []


async def run_scraper():
    print("🚀 1. AŞAMA: Tüm teşvik siteleri asenkron olarak taranıyor...\n")
    all_announcements = []
    async with httpx.AsyncClient() as client:
        tasks = [fetch_site(client, site) for site in TARGETS]
        results = await asyncio.gather(*tasks)
        for result_list in results:
            all_announcements.extend(result_list)

    # Önceki verilerle birleştir (eğer varsa)
    existing = []
    if os.path.exists('tesvik_duyurulari.json'):
        try:
            with open('tesvik_duyurulari.json', 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except Exception:
            existing = []

    # Yeni verileri öne ekle, duplicate title'ları çıkar
    seen_titles = set()
    combined = []
    for item in all_announcements + existing:
        if item['title'] not in seen_titles and item['title'] != "Başlık Bulunamadı":
            seen_titles.add(item['title'])
            combined.append(item)

    with open('tesvik_duyurulari.json', 'w', encoding='utf-8') as f:
        json.dump(combined, f, ensure_ascii=False, indent=4)

    print(f"\n✨ Tarama bitti! {len(combined)} adet benzersiz veri kaydedildi.")
    return len(combined)


# ===================================================================
# 2. ÖN YÜZ: HTML ARAYÜZ ŞABLONU (FRONTEND)
# ===================================================================
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Teşvik ve Destek Radarı | Aimtas</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .hover-card { transition: transform 0.2s ease-in-out, box-shadow 0.2s ease-in-out; }
        .hover-card:hover { transform: translateY(-4px); box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); }
    </style>
</head>
<body class="bg-slate-50 font-sans text-slate-800">
    <header class="bg-blue-600 text-white shadow-md">
        <div class="max-w-7xl mx-auto px-4 py-6 flex justify-between items-center">
            <div>
                <h1 class="text-3xl font-bold tracking-tight">Teşvik Radarı</h1>
                <p class="text-blue-100 text-sm mt-1">Girişimciler için tek ekranda güncel devlet destekleri</p>
            </div>
            <div class="text-xl font-bold">Aimtas.</div>
        </div>
    </header>

    <!-- Filtre Çubuğu -->
    <div class="max-w-7xl mx-auto px-4 pt-6 pb-2 flex flex-wrap gap-2" id="filter-bar">
        <button onclick="filterSource('Tümü')" class="filter-btn active px-4 py-2 rounded-full text-sm font-semibold bg-blue-600 text-white" data-source="Tümü">Tümü</button>
    </div>

    <main class="max-w-7xl mx-auto px-4 py-6">
        <div id="loading" class="text-center py-20">
            <div class="inline-block animate-spin rounded-full h-10 w-10 border-4 border-blue-500 border-t-transparent mb-4"></div>
            <p class="text-lg text-slate-500 font-semibold">Duyurular getiriliyor...</p>
        </div>
        <div id="empty-state" class="hidden text-center py-20">
            <p class="text-5xl mb-4">📭</p>
            <p class="text-xl font-bold text-slate-600">Henüz veri yok</p>
            <p class="text-slate-400 mt-2">Sunucu yeni başlatıldı, veriler çekilemedi.<br>Sayfayı yenileyin veya birkaç dakika bekleyin.</p>
        </div>
        <div id="announcement-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 hidden"></div>
    </main>

    <script>
        let allData = [];
        const grid = document.getElementById('announcement-grid');
        const loading = document.getElementById('loading');
        const emptyState = document.getElementById('empty-state');
        const filterBar = document.getElementById('filter-bar');

        const sourceColors = {
            'KOSGEB':            'bg-blue-100 text-blue-700',
            'TÜBİTAK':           'bg-red-100 text-red-700',
            'Sanayi Bakanlığı':  'bg-amber-100 text-amber-700',
            'Hazine ve Maliye':  'bg-emerald-100 text-emerald-700',
        };

        function badgeClass(source) {
            for (const key of Object.keys(sourceColors)) {
                if (source.includes(key)) return sourceColors[key];
            }
            return 'bg-slate-200 text-slate-700';
        }

        function renderCards(data) {
            grid.innerHTML = '';
            if (!data.length) { emptyState.classList.remove('hidden'); grid.classList.add('hidden'); return; }
            emptyState.classList.add('hidden');
            grid.classList.remove('hidden');
            data.forEach(item => {
                const card = document.createElement('div');
                card.className = 'bg-white rounded-lg p-6 shadow-sm border border-slate-200 hover-card flex flex-col justify-between';
                card.innerHTML = `
                    <div>
                        <span class="inline-block px-3 py-1 text-xs font-semibold rounded-full ${badgeClass(item.source)} mb-4">${item.source}</span>
                        <h2 class="text-base font-bold text-slate-800 leading-snug mb-3">${item.title}</h2>
                    </div>
                    <div class="mt-6 flex items-center justify-between">
                        <span class="text-xs text-slate-400">📅 ${item.scraped_at.split(' ')[0]}</span>
                        <a href="${item.url}" target="_blank" rel="noopener" class="text-blue-600 font-semibold text-sm hover:text-blue-800 flex items-center gap-1">İncele &rarr;</a>
                    </div>`;
                grid.appendChild(card);
            });
        }

        function filterSource(source) {
            document.querySelectorAll('.filter-btn').forEach(btn => {
                btn.classList.remove('bg-blue-600', 'text-white');
                btn.classList.add('bg-white', 'text-slate-600', 'border', 'border-slate-200');
            });
            const active = document.querySelector(`.filter-btn[data-source="${source}"]`);
            if (active) { active.classList.add('bg-blue-600', 'text-white'); active.classList.remove('bg-white', 'text-slate-600', 'border', 'border-slate-200'); }
            const filtered = source === 'Tümü' ? allData : allData.filter(d => d.source === source);
            renderCards(filtered);
        }

        document.addEventListener('DOMContentLoaded', () => {
            fetch('tesvik_duyurulari.json?t=' + Date.now())
                .then(res => res.json())
                .then(data => {
                    allData = data;
                    loading.classList.add('hidden');

                    // Kaynak butonlarını oluştur
                    const sources = [...new Set(data.map(d => d.source))];
                    sources.forEach(src => {
                        const btn = document.createElement('button');
                        btn.className = 'filter-btn px-4 py-2 rounded-full text-sm font-semibold bg-white text-slate-600 border border-slate-200';
                        btn.dataset.source = src;
                        btn.textContent = src;
                        btn.onclick = () => filterSource(src);
                        filterBar.appendChild(btn);
                    });

                    renderCards(data);
                })
                .catch(() => {
                    loading.classList.add('hidden');
                    emptyState.classList.remove('hidden');
                });
        });
    </script>
</body>
</html>
"""


# ===================================================================
# 3. WEB SUNUCUSUNU BAŞLATMA MANTIĞI
# ===================================================================
def start_server(port=8000):
    # Arayüz için index.html dosyasını otomatik oluştur
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(HTML_TEMPLATE)

    Handler = http.server.SimpleHTTPRequestHandler
    socketserver.TCPServer.allow_reuse_address = True

    with socketserver.TCPServer(("", port), Handler) as httpd:
        print(f"\n🖥️  2. AŞAMA: Yerel Web Sunucusu Başlatıldı!")
        print(f"🔗 Tarayıcınızı açın ve şu adrese gidin: http://localhost:{port}")
        print("⌨️  Kapatmak için Terminalde CTRL+C tuşlarına basın.\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nSunucu kapatılıyor...")


# ===================================================================
# 4. ÇALIŞTIRICI
# ===================================================================
if __name__ == "__main__":
    count = asyncio.run(run_scraper())
    start_server(port=8000)
