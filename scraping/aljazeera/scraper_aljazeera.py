"""
Al Jazeera scraper
==================
Usa Playwright per caricare tutte le pagine di sezione,
poi estrae titolo, link, source, timestamp e descrizione con BeautifulSoup.

NON clicca "Show more" – legge solo le notizie già presenti nella pagina
usando i pattern HTML definiti in index.html (righe 1-2):

  Riga 1 – article-card--highlighted:
    <article class="article-card--reset article-card--highlighted">
      <a class="u-clickable-card__link article-card__link" href="…">
        <h2 class="article-card__title"><span>…</span></h2>
      </a>
      <p class="article-card__excerpt"><span>…</span></p>
      <div class="date-simple">
        <span aria-hidden="true">28 Apr 2026</span>
      </div>
    </article>

  Riga 2 – gc--list article-card--home-page-feed:
    <article class="gc--list article-card--home-page-feed article-card …">
      (stessa struttura interna)
    </article>

Pagine da scrapare (da index.html righe 8-9):
  News:  /news/, /africa/, /asia/, /us-canada/, /latin-america/, /europe/, /asia-pacific/
  More:  /features/, /economy/, /tag/human-rights/, /climate-crisis,
         /investigations/, /interactives/, /gallery/,
         /tag/science-and-technology/

Uso:
  python scraper_aljazeera.py
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

# ── configurazione ──────────────────────────────────────────────────
BASE_URL = "https://www.aljazeera.com"
OUTPUT_FILE = Path(__file__).parent / "articles.json"

# Tutte le sezioni da scrapare (righe 8-9 di index.html)
SECTIONS = [
    # Riga 8 – News submenu
    "/news/",
    "/africa/",
    "/asia/",
    "/us-canada/",
    "/latin-america/",
    "/europe/",
    "/asia-pacific/",
    # Riga 9 – More submenu
    "/features/",
    "/economy/",
    "/tag/human-rights/",
    "/climate-crisis",
    "/investigations/",
    "/interactives/",
    "/gallery/",
    "/tag/science-and-technology/",
]


# ── helpers ─────────────────────────────────────────────────────────

def _accept_cookies(page) -> None:
    """Chiude eventuali banner cookie / consent."""
    selectors = [
        'button#onetrust-accept-btn-handler',
        'button:has-text("Allow all")',
        'button:has-text("Accept All")',
        'button:has-text("Accept")',
        'button:has-text("Accetta")',
        'button:has-text("I Agree")',
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


SHOW_MORE_SELECTOR = 'button[data-testid="show-more-button"]'
SHOW_MORE_CLICKS = 3  # click "Show more" 3 volte per pagina


def _click_show_more(page) -> bool:
    """Clicca il bottone 'Show more' se presente. Ritorna True se cliccato."""
    try:
        btn = page.locator(SHOW_MORE_SELECTOR).first
        if btn.is_visible(timeout=3_000):
            btn.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            btn.click()
            page.wait_for_timeout(2_500)
            return True
    except (PwTimeout, Exception):
        pass
    return False


def _fetch_section_html(page, section_path: str) -> str:
    """Naviga verso una sezione, attende il caricamento, clicca 'Show more' 3 volte e ritorna HTML."""
    url = BASE_URL + section_path
    print(f"\n[*] Navigazione verso {url} …")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(3_000)
    except PwTimeout:
        print(f"[✗] Timeout navigando verso {url}")
        return ""

    # accetta cookie (solo la prima volta, ma non fa male riprovare)
    _accept_cookies(page)

    # attendi che gli articoli siano caricati (entrambi i pattern)
    # Riga 1: sezione featured → <li class="themed-featured-posts-list__item">
    #         contiene <article class="article-card--reset ...">
    # Riga 2: sezione feed → <article class="gc--list article-card ...">
    try:
        page.wait_for_selector(
            "article.article-card--reset, article.article-card",
            timeout=10_000,
        )
    except PwTimeout:
        print(f"[!] Nessun articolo trovato in {section_path}")
        return page.content()

    # scrolla la pagina per caricare eventuali contenuti lazy
    for scroll_step in range(5):
        page.evaluate(f"window.scrollTo(0, {(scroll_step + 1) * 1500})")
        page.wait_for_timeout(600)

    initial_count = page.locator("article.article-card--reset, article.article-card").count()
    print(f"[✓] {initial_count} articoli trovati inizialmente")

    # clicca "Show more" 3 volte per caricare più articoli dal feed
    for click_num in range(1, SHOW_MORE_CLICKS + 1):
        if not _click_show_more(page):
            print(f"    ↳ Bottone 'Show more' non trovato, stop dopo {click_num - 1} click.")
            break

        # scrolla per triggerare lazy loading dei nuovi articoli
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1_000)

        count = page.locator("article.article-card--reset, article.article-card").count()
        print(f"    ↳ Show more #{click_num} — {count} articoli totali")

    # torna su
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)

    html = page.content()
    return html


# ── parsing ─────────────────────────────────────────────────────────

def _parse_date(date_text: str) -> str:
    """
    Converte date Al Jazeera in formato ISO.
    Formati tipici: "28 Apr 2026", "Published On 28 Apr 2026"
    """
    if not date_text:
        return ""

    # rimuovi "Published On " se presente
    clean = date_text.replace("Published On ", "").strip()

    # prova vari formati
    for fmt in ["%d %b %Y", "%B %d, %Y", "%d %B %Y"]:
        try:
            dt = datetime.strptime(clean, fmt)
            return dt.strftime("%Y-%m-%dT00:00:00+00:00")
        except ValueError:
            continue

    return clean  # ritorna il testo originale se non riesce a parsare


def parse_articles_from_html(html: str, source: str) -> list[dict]:
    """
    Estrae gli articoli dall'HTML di una sezione usando i pattern
    trovati in index.html (righe 1-2):
      - Riga 1: sezione featured (themed-featured-posts-list__item)
                <article class="article-card--reset ...">
      - Riga 2: sezione feed
                <article class="gc--list article-card ...">
    """
    soup = BeautifulSoup(html, "html.parser")

    # Trova TUTTI gli articoli che matchano almeno uno dei due pattern:
    #   - article-card--reset  (sezione featured/top, riga 1)
    #   - article-card         (feed list, riga 2)
    cards = soup.find_all(
        "article",
        class_=lambda c: c and (
            "article-card--reset" in c.split() or "article-card" in c.split()
        ),
    )

    articles: list[dict] = []

    for card in cards:
        # ── Link ───────────────────────────────────────────────────
        link_tag = card.find("a", class_="u-clickable-card__link")
        if not link_tag:
            continue

        href = link_tag.get("href", "")
        if href and not href.startswith("http"):
            href = BASE_URL + href

        # ── Titolo ─────────────────────────────────────────────────
        title_tag = card.find(class_="article-card__title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        if not title:
            continue

        # ── Descrizione ────────────────────────────────────────────
        desc_tag = card.find("p", class_="article-card__excerpt")
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        # ── Data / Timestamp ───────────────────────────────────────
        date_div = card.find("div", class_="date-simple")
        timestamp = ""
        if date_div:
            # prendi lo span con aria-hidden="true" che ha la data visibile
            visible_span = date_div.find("span", attrs={"aria-hidden": "true"})
            if visible_span:
                timestamp = _parse_date(visible_span.get_text(strip=True))
            else:
                # fallback: screen-reader-text
                sr_span = date_div.find("span", class_="screen-reader-text")
                if sr_span:
                    timestamp = _parse_date(sr_span.get_text(strip=True))

        articles.append({
            "title": title,
            "link": href,
            "source": source,
            "timestamp": timestamp,
            "description": description,
        })

    return articles


# ── main ────────────────────────────────────────────────────────────

def main() -> None:
    all_articles: list[dict] = []
    seen_links: set[str] = set()  # deduplicazione per URL

    with sync_playwright() as pw:
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
        page = context.new_page()

        total_sections = len(SECTIONS)
        for idx, section in enumerate(SECTIONS, 1):
            # usa il nome della sezione come source
            source_name = section.strip("/").split("/")[-1]
            if not source_name:
                source_name = section.strip("/")

            print(f"\n{'═' * 70}")
            print(f"[{idx}/{total_sections}] Scraping: {source_name} → {section}")
            print(f"{'═' * 70}")

            html = _fetch_section_html(page, section)
            if not html:
                continue

            section_articles = parse_articles_from_html(html, source_name)
            print(f"    → {len(section_articles)} articoli estratti da {section}")

            # deduplicazione globale
            new_count = 0
            for article in section_articles:
                if article["link"] not in seen_links:
                    seen_links.add(article["link"])
                    all_articles.append(article)
                    new_count += 1

            dupes = len(section_articles) - new_count
            if dupes:
                print(f"    → {dupes} duplicati scartati")
            print(f"    → {new_count} nuovi articoli aggiunti")

        browser.close()

    # ordina per timestamp (più recenti prima), articoli senza timestamp in fondo
    all_articles.sort(
        key=lambda a: a["timestamp"] if a["timestamp"] else "0000",
        reverse=True,
    )

    # salva su file JSON
    output = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "total_articles": len(all_articles),
        "articles": all_articles,
    }
    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # riepilogo per fonte
    print(f"\n{'═' * 70}")
    print(f"[✓] Salvati {len(all_articles)} articoli in {OUTPUT_FILE}")
    print(f"\n{'─' * 70}")
    print(f"{'FONTE':<22} {'ARTICOLI':>10}")
    print(f"{'─' * 70}")
    from collections import Counter
    counts = Counter(a["source"] for a in all_articles)
    for source, count in sorted(counts.items()):
        print(f"{source:<22} {count:>10}")
    print(f"{'─' * 70}")
    print(f"{'TOTALE':<22} {len(all_articles):>10}")

    # stampa i primi 20 articoli come anteprima
    print(f"\n{'─' * 90}")
    print(f"{'TITOLO':<55} {'SOURCE':<20} {'DATA'}")
    print(f"{'─' * 90}")
    for a in all_articles[:20]:
        ts = a["timestamp"][:10] if a["timestamp"] else "N/A"
        print(f"{a['title'][:53]:<55} {a['source']:<20} {ts}")
    if len(all_articles) > 20:
        print(f"    … e altri {len(all_articles) - 20} articoli")
    print(f"{'─' * 90}")


if __name__ == "__main__":
    main()
