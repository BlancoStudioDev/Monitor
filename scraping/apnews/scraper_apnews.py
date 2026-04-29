"""
AP News scraper
===============
Usa Playwright per caricare le pagine hub di AP News con rendering JS,
poi estrae le notizie dai container principali con BeautifulSoup.

Container estratti:
  • FourColumnContainer-container  (griglie a 4 colonne con sottocategorie)
  • PageListStandardH              (lista orizzontale di notizie)
  • TwoColumnContainer7030         (layout 70-30)
  • flickity-slider                (solo per la pagina /technology)

⚠ AP News può bloccare richieste automatizzate – alla prima esecuzione
  potrebbe apparire un CAPTCHA nel browser: risolvilo manualmente,
  lo scraper aspetterà fino a 3 minuti.

Uso:
  python scraper_apnews.py            # Chrome col tuo profilo via CDP
  python scraper_apnews.py --clean    # Chromium pulito (headed)
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
from playwright_stealth import Stealth

# ── configurazione ──────────────────────────────────────────────────
BASE_URL = "https://apnews.com"
OUTPUT_FILE = Path(__file__).parent / "articles.json"
CDP_PORT = 9222

PAGES = {
    "asia-pacific":      f"{BASE_URL}/hub/asia-pacific",
    "europe":            f"{BASE_URL}/hub/europe",
    "china":             f"{BASE_URL}/hub/china",
    "russia-ukraine":    f"{BASE_URL}/hub/russia-ukraine",
    "latin-america":     f"{BASE_URL}/hub/latin-america",
    "africa":            f"{BASE_URL}/hub/africa",
    "us-news":           f"{BASE_URL}/us-news",
    "elections":         f"{BASE_URL}/hub/elections",
    "tariffs":           f"{BASE_URL}/hub/tariffs",
    "financial-markets": f"{BASE_URL}/hub/financial-markets",
    "technology":        f"{BASE_URL}/technology",
    "inflation":         f"{BASE_URL}/hub/inflation",
    "financial-wellness":f"{BASE_URL}/hub/financial-wellness",
}

# Classi CSS dei container da cui estrarre le notizie
CONTAINER_CLASSES = [
    "FourColumnContainer-container",
    "PageListStandardH",
    "TwoColumnContainer7030",
]
# flickity-slider viene aggiunto solo per la pagina technology
TECH_EXTRA_CLASS = "flickity-slider"

stealth = Stealth(
    navigator_platform_override="MacIntel",
    navigator_vendor_override="Google Inc.",
)

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


# ── helpers ─────────────────────────────────────────────────────────

def _normalize_url(href: str) -> str:
    """Converte href relativi in URL assoluti di apnews.com."""
    if not href:
        return ""
    if href.startswith("http"):
        return href
    return urljoin(BASE_URL, href)


def _accept_cookies(page) -> None:
    """Chiude eventuali banner cookie / consent."""
    selectors = [
        'button#onetrust-accept-btn-handler',
        'button:has-text("Accept All")',
        'button:has-text("Accept")',
        'button:has-text("Accetta")',
        'button:has-text("I Agree")',
        'button:has-text("Agree")',
    ]
    for sel in selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=2_000):
                btn.click()
                page.wait_for_timeout(500)
                return
        except (PwTimeout, Exception):
            continue


def _is_blocked(page) -> bool:
    """Verifica se la pagina è bloccata (CAPTCHA, Cloudflare, etc.)."""
    has_content = page.locator('.PagePromo-title').count() > 0
    if has_content:
        return False
    html = page.content()
    blocked_signals = [
        "captcha-delivery.com",
        "challenge-platform",
        "cf-browser-verification",
        "access denied",
    ]
    html_lower = html.lower()
    return any(sig in html_lower for sig in blocked_signals)


def _wait_for_captcha_resolution(page, timeout_seconds: int = 180) -> bool:
    """Attende che l'utente risolva il CAPTCHA manualmente."""
    print(f"[!] Pagina bloccata – risolvila nel browser (timeout: {timeout_seconds}s) …")
    waited = 0
    interval = 3
    while waited < timeout_seconds:
        page.wait_for_timeout(interval * 1000)
        waited += interval
        if not _is_blocked(page):
            print("[✓] Blocco risolto!")
            return True
    return False


# ── Chrome launcher ─────────────────────────────────────────────────

def _kill_chrome():
    """Chiude tutti i processi Chrome."""
    subprocess.run(["pkill", "-f", "Google Chrome"], capture_output=True)
    time.sleep(2)


def _is_cdp_ready() -> bool:
    """Verifica se Chrome risponde sulla porta CDP."""
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2)
        return resp.status == 200
    except Exception:
        return False


def _launch_chrome_with_cdp():
    """
    Avvia Chrome con --remote-debugging-port.
    Se Chrome è già in ascolto sulla porta CDP, lo riusa.
    """
    if _is_cdp_ready():
        print(f"[✓] Chrome già in ascolto sulla porta {CDP_PORT}, riuso sessione esistente")
        return None

    print("[*] Chiusura di Chrome in corso …")
    _kill_chrome()

    print(f"[*] Avvio Chrome con debug port {CDP_PORT} …")

    scraper_profile = Path(__file__).parent / ".chrome_scraper_profile"
    scraper_profile.mkdir(exist_ok=True)

    proc = subprocess.Popen(
        [
            CHROME_PATH,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={scraper_profile}",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(30):
        if _is_cdp_ready():
            print(f"[✓] Chrome pronto sulla porta {CDP_PORT}")
            return proc
        time.sleep(1)

    print("[✗] Chrome non risponde sulla porta CDP.")
    proc.kill()
    sys.exit(1)


# ── browser launchers ───────────────────────────────────────────────

def _launch_clean(pw):
    """Lancia un browser Chromium pulito (headed) con stealth."""
    browser = pw.chromium.launch(
        headless=False,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="Europe/Rome",
    )
    stealth.apply_stealth_sync(context)
    page = context.new_page()
    return browser, page


def _connect_cdp(pw):
    """Si connette a Chrome via CDP su 127.0.0.1."""
    cdp_url = f"http://127.0.0.1:{CDP_PORT}"
    browser = pw.chromium.connect_over_cdp(cdp_url)
    context = browser.contexts[0] if browser.contexts else browser.new_context()
    page = context.pages[0] if context.pages else context.new_page()
    return browser, page


# ── parsing ─────────────────────────────────────────────────────────

def _extract_articles_from_container(container, source: str) -> list[dict]:
    """
    Estrae le notizie da un container BeautifulSoup.
    Ogni notizia è un <div class="PagePromo"> con un <h3 class="PagePromo-title">
    che contiene un <a> con href e titolo.
    """
    articles = []
    promos = container.find_all("div", class_="PagePromo")

    for promo in promos:
        # Trova il titolo e il link dentro PagePromo-title
        title_h3 = promo.find(class_="PagePromo-title")
        if not title_h3:
            continue

        link_tag = title_h3.find("a", class_="Link")
        if not link_tag:
            continue

        href = _normalize_url(link_tag.get("href", ""))
        if not href or "/article/" not in href:
            continue

        # Estrai il titolo dal testo dello span interno
        title_span = link_tag.find("span", class_="PagePromoContentIcons-text")
        title = title_span.get_text(strip=True) if title_span else link_tag.get_text(strip=True)

        if not title:
            continue

        # Estrai timestamp se disponibile
        timestamp_tag = promo.find("bsp-timestamp")
        timestamp = ""
        if timestamp_tag and timestamp_tag.get("data-timestamp"):
            try:
                ts_ms = int(timestamp_tag["data-timestamp"])
                dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
                timestamp = dt.isoformat()
            except (ValueError, OSError):
                pass

        # Estrai descrizione se disponibile
        desc_div = promo.find(class_="PagePromo-description")
        description = ""
        if desc_div:
            desc_span = desc_div.find("span", class_="PagePromoContentIcons-text")
            description = desc_span.get_text(strip=True) if desc_span else desc_div.get_text(strip=True)

        articles.append({
            "title": title,
            "link": href,
            "source": source,
            "timestamp": timestamp,
            "description": description,
        })

    return articles


def parse_page(html: str, page_name: str) -> list[dict]:
    """
    Parsa l'HTML di una pagina AP News ed estrae gli articoli
    dai container specificati.
    """
    soup = BeautifulSoup(html, "html.parser")
    all_articles = []

    # Classi base + extra per technology
    classes_to_search = list(CONTAINER_CLASSES)
    if page_name == "technology":
        classes_to_search.append(TECH_EXTRA_CLASS)

    for css_class in classes_to_search:
        containers = soup.find_all(class_=css_class)
        for container in containers:
            articles = _extract_articles_from_container(container, page_name)
            all_articles.extend(articles)

    return all_articles


# ── page fetching ───────────────────────────────────────────────────

def fetch_all_pages(use_clean: bool = False) -> list[dict]:
    """Carica tutte le pagine e ritorna la lista di articoli."""
    chrome_proc = None
    all_articles = []
    seen_links: set[str] = set()  # deduplicazione globale per URL

    if not use_clean:
        chrome_proc = _launch_chrome_with_cdp()

    try:
        with sync_playwright() as pw:
            if use_clean:
                print("[*] Avvio browser Chromium pulito (headed) …")
                closeable, page = _launch_clean(pw)
            else:
                print("[*] Connessione a Chrome via CDP …")
                closeable, page = _connect_cdp(pw)

            total_pages = len(PAGES)
            for idx, (page_name, url) in enumerate(PAGES.items(), 1):
                print(f"\n{'═' * 70}")
                print(f"[{idx}/{total_pages}] Scraping: {page_name} → {url}")
                print(f"{'═' * 70}")

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    page.wait_for_timeout(4_000)

                    # controlla blocchi
                    if _is_blocked(page):
                        if not _wait_for_captcha_resolution(page, timeout_seconds=180):
                            print(f"[✗] Timeout per {page_name}, skip.")
                            continue
                        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                        page.wait_for_timeout(4_000)

                    # gestisci cookie banner (solo alla prima pagina di solito)
                    if idx == 1:
                        _accept_cookies(page)

                    # scrollo la pagina per caricare i contenuti lazy
                    for scroll_step in range(5):
                        page.evaluate(f"window.scrollTo(0, {(scroll_step + 1) * 1500})")
                        page.wait_for_timeout(800)

                    # torna su
                    page.evaluate("window.scrollTo(0, 0)")
                    page.wait_for_timeout(500)

                    html = page.content()
                    articles = parse_page(html, page_name)

                    # deduplicazione
                    new_articles = []
                    for art in articles:
                        if art["link"] not in seen_links:
                            seen_links.add(art["link"])
                            new_articles.append(art)

                    all_articles.extend(new_articles)
                    print(f"[✓] {len(new_articles)} nuovi articoli da {page_name} "
                          f"({len(articles) - len(new_articles)} duplicati rimossi)")

                except PwTimeout:
                    print(f"[✗] Timeout caricamento {page_name}, skip.")
                except Exception as e:
                    print(f"[✗] Errore su {page_name}: {e}")

            closeable.close()

    finally:
        if chrome_proc:
            chrome_proc.terminate()
            try:
                chrome_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome_proc.kill()

    return all_articles


# ── main ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AP News scraper – estrae notizie dalle pagine hub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi d'uso:
  # Usa il tuo Chrome con profilo reale (consigliato)
  python scraper_apnews.py

  # Browser Chromium pulito (potrebbe essere bloccato)
  python scraper_apnews.py --clean
""",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Usa un browser Chromium pulito invece del tuo Chrome",
    )
    args = parser.parse_args()

    articles = fetch_all_pages(use_clean=args.clean)

    # salva su file JSON
    output = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "total_articles": len(articles),
        "articles": articles,
    }

    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\n{'═' * 70}")
    print(f"[✓] Salvati {len(articles)} articoli in {OUTPUT_FILE}")

    # riepilogo per fonte
    print(f"\n{'─' * 70}")
    print(f"{'FONTE':<22} {'ARTICOLI':>10}")
    print(f"{'─' * 70}")
    from collections import Counter
    counts = Counter(a["source"] for a in articles)
    for source, count in sorted(counts.items()):
        print(f"{source:<22} {count:>10}")
    print(f"{'─' * 70}")
    print(f"{'TOTALE':<22} {len(articles):>10}")

    # stampa i primi 20 articoli come anteprima
    print(f"\n{'─' * 90}")
    print(f"{'TITOLO':<55} {'FONTE':<18} {'LINK'}")
    print(f"{'─' * 90}")
    for a in articles[:20]:
        print(f"{a['title'][:53]:<55} {a['source']:<18} {a['link'][:50]}")
    if len(articles) > 20:
        print(f"  … e altri {len(articles) - 20} articoli")
    print(f"{'─' * 90}")


if __name__ == "__main__":
    main()
