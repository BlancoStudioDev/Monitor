"""
Reuters /world/ scraper
========================
Usa Playwright per caricare la pagina con rendering JS,
clicca "Load More" fino a raggiungere articoli vecchi di 24 ore,
poi estrae titolo, ora, nazione e descrizione con BeautifulSoup.

⚠ Reuters usa DataDome anti-bot: alla prima esecuzione potrebbe
  apparire un CAPTCHA nel browser – risolvilo manualmente,
  lo scraper aspetterà fino a 3 minuti.

Uso:
  python scraper_reuters.py            # apre Chrome col tuo profilo
  python scraper_reuters.py --clean    # apre un browser Chromium pulito
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
from playwright_stealth import Stealth

# ── configurazione ──────────────────────────────────────────────────
URL = "https://www.reuters.com/world/"
CUTOFF = datetime.now(timezone.utc) - timedelta(hours=24)
OUTPUT_FILE = Path(__file__).parent / "articles.json"
MAX_LOAD_MORE_CLICKS = 50
MIN_LOAD_MORE_CLICKS = 4  # minimo di click prima di controllare il cutoff 24h
LOAD_MORE_SELECTOR = (
    'button[data-testid="LoadMore"], '
    'button:has-text("Load More"), '
    'button:has-text("Load more"), '
    'button:has-text("Load more articles")'
)
CDP_PORT = 9222

stealth = Stealth(
    navigator_platform_override="MacIntel",
    navigator_vendor_override="Google Inc.",
)

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_USER_DATA = os.path.expanduser(
    "~/Library/Application Support/Google/Chrome"
)


# ── helpers ─────────────────────────────────────────────────────────

def _accept_cookies(page) -> None:
    """Chiude eventuali banner cookie / consent."""
    selectors = [
        'button#onetrust-accept-btn-handler',
        'button[data-testid="AcceptCookiesButton"]',
        'button:has-text("Accept All")',
        'button:has-text("Accetta")',
        'button:has-text("I Agree")',
        'button:has-text("Accept")',
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


def _click_load_more(page) -> bool:
    """Clicca il bottone 'Load More' se presente. Ritorna True se cliccato."""
    try:
        btn = page.locator(LOAD_MORE_SELECTOR).first
        if btn.is_visible(timeout=3_000):
            btn.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            btn.click()
            page.wait_for_timeout(2_500)
            return True
    except (PwTimeout, Exception):
        pass
    return False


def _oldest_datetime_on_page(page) -> datetime | None:
    """Restituisce il datetime più vecchio tra tutti gli articoli visibili."""
    times = page.locator('[data-testid="DateLineText"]').all()
    oldest = None
    for t in times:
        raw = t.get_attribute("datetime")
        if raw:
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if oldest is None or dt < oldest:
                    oldest = dt
            except ValueError:
                continue
    return oldest


def _is_captcha_blocked(page) -> bool:
    """
    Verifica se la pagina è effettivamente bloccata da un CAPTCHA DataDome.
    Controlla la presenza dell'iframe captcha-delivery.com E l'assenza
    di contenuto articoli. Evita falsi positivi da script/cookie.
    """
    has_articles = page.locator('[data-testid="FeedListItem"]').count() > 0
    if has_articles:
        return False  # articoli presenti → nessun blocco
    # cerca l'iframe specifico di DataDome o il titolo generico di blocco
    html = page.content()
    return "captcha-delivery.com" in html or "<title>reuters.com</title>" in html.lower()


def _wait_for_captcha_resolution(page, timeout_seconds: int = 180) -> bool:
    """Attende che l'utente risolva il CAPTCHA manualmente nel browser."""
    print(f"[!] CAPTCHA rilevato – risolvilo nel browser (timeout: {timeout_seconds}s) …")
    waited = 0
    interval = 3
    while waited < timeout_seconds:
        page.wait_for_timeout(interval * 1000)
        waited += interval
        if not _is_captcha_blocked(page):
            print("[✓] CAPTCHA risolto!")
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
    Se Chrome è già in ascolto sulla porta CDP, lo riusa senza riavviare
    (così i cookie DataDome persistono tra le esecuzioni).
    """
    # se Chrome è già pronto con CDP, non riavviarlo
    if _is_cdp_ready():
        print(f"[✓] Chrome già in ascolto sulla porta {CDP_PORT}, riuso sessione esistente")
        return None  # nessun processo da terminare

    print("[*] Chiusura di Chrome in corso …")
    _kill_chrome()

    print(f"[*] Avvio Chrome con debug port {CDP_PORT} …")

    # Chrome richiede --user-data-dir con --remote-debugging-port.
    # Usiamo un profilo dedicato che persiste i cookie DataDome tra le esecuzioni.
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

    # aspetta che la porta CDP sia pronta
    for i in range(30):
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


# ── page fetching ───────────────────────────────────────────────────

def fetch_page_html(use_clean: bool = False) -> str:
    """Carica la pagina, espande fino a 24h e ritorna l'HTML."""
    chrome_proc = None

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

            print(f"[*] Navigazione verso {URL} …")
            page.goto(URL, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(5_000)

            # controlla se la pagina è bloccata da un CAPTCHA DataDome
            if _is_captcha_blocked(page):
                if not _wait_for_captcha_resolution(page, timeout_seconds=180):
                    print("[✗] Timeout: il CAPTCHA non è stato risolto.")
                    closeable.close()
                    sys.exit(1)
                # dopo il captcha, ricarica
                page.goto(URL, wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(5_000)

            # gestisci cookie banner
            _accept_cookies(page)

            # attendi che gli articoli siano caricati
            try:
                page.wait_for_selector('[data-testid="FeedListItem"]', timeout=15_000)
                count = page.locator('[data-testid="FeedListItem"]').count()
                print(f"[✓] {count} articoli trovati nella pagina!")
            except PwTimeout:
                print("[!] Nessun articolo trovato nella pagina.")
                html = page.content()
                debug_path = Path(__file__).with_name("debug_page.html")
                debug_path.write_text(html, encoding="utf-8")
                print(f"    HTML di debug salvato in {debug_path}")
                closeable.close()
                sys.exit(1)

            # clicca "Load More" finché l'articolo più vecchio non supera le 24h
            # facciamo almeno MIN_LOAD_MORE_CLICKS per caricare abbastanza articoli
            clicks = 0
            while clicks < MAX_LOAD_MORE_CLICKS:
                # controlla il cutoff solo dopo il minimo di click
                if clicks >= MIN_LOAD_MORE_CLICKS:
                    oldest = _oldest_datetime_on_page(page)
                    if oldest and oldest < CUTOFF:
                        print(f"[✓] Raggiunto il cutoff 24h (articolo più vecchio: {oldest.isoformat()})")
                        break
                else:
                    oldest = _oldest_datetime_on_page(page)

                if not _click_load_more(page):
                    print("[!] Bottone 'Load More' non trovato, stop.")
                    break

                clicks += 1
                count = page.locator('[data-testid="FeedListItem"]').count()
                print(f"    ↳ Load More #{clicks} — {count} articoli caricati (oldest: {oldest})")

            html = page.content()
            closeable.close()
            return html

    finally:
        # chiudi Chrome lanciato da noi
        if chrome_proc:
            chrome_proc.terminate()
            chrome_proc.wait(timeout=5)


# ── parsing ─────────────────────────────────────────────────────────

def parse_articles(html: str) -> list[dict]:
    """Parsa l'HTML con BeautifulSoup ed estrae gli articoli delle ultime 24h."""
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.find_all("li", attrs={"data-testid": "FeedListItem"})
    print(f"[*] Trovati {len(cards)} story-card totali nella pagina.")

    articles: list[dict] = []
    seen: set[str] = set()  # deduplicazione per URL articolo

    for card in cards:
        # ── URL articolo (per deduplicazione) ──────────────────────
        link_tag = card.find("a", attrs={"data-testid": "TitleLink"})
        article_url = link_tag.get("href", "") if link_tag else ""

        # salta duplicati (stessa notizia in hero + feed o sezioni diverse)
        if article_url and article_url in seen:
            continue
        if article_url:
            seen.add(article_url)

        # ── datetime ───────────────────────────────────────────────
        time_tag = card.find("time", attrs={"data-testid": "DateLineText"})
        if not time_tag:
            continue
        raw_dt = time_tag.get("datetime", "")
        try:
            article_dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
        except ValueError:
            continue

        # filtra: solo ultime 24h
        if article_dt < CUTOFF:
            continue

        # ── titolo ─────────────────────────────────────────────────
        title_tag = card.find(attrs={"data-testid": "TitleHeading"})
        title = title_tag.get_text(strip=True) if title_tag else ""

        # ── nazione / kicker ───────────────────────────────────────
        kicker_tag = card.find("a", attrs={"data-testid": "KickerLink"})
        if kicker_tag:
            visible_texts = []
            for child in kicker_tag.children:
                # salta lo <span> nascosto con clip-path che contiene "category"
                if hasattr(child, "get") and child.get("style", "").find("clip") != -1:
                    continue
                text = child if isinstance(child, str) else child.get_text(strip=True)
                text = str(text).strip()
                if text and text.lower() != "category":
                    visible_texts.append(text)
            country = " ".join(visible_texts) if visible_texts else ""
        else:
            country = ""

        # ── descrizione ────────────────────────────────────────────
        desc_tag = card.find(attrs={"data-testid": "Description"})
        description = desc_tag.get_text(strip=True) if desc_tag else ""

        articles.append({
            "title": title,
            "datetime": article_dt.isoformat(),
            "time_ago": time_tag.get_text(strip=True),
            "country": country,
            "description": description,
        })

    print(f"    → {len(seen)} articoli unici (scartati {len(cards) - len(articles)} duplicati)")
    return articles


# ── main ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reuters /world/ scraper – estrae articoli delle ultime 24h",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi d'uso:
  # Usa il tuo Chrome con profilo reale (consigliato)
  python scraper_reuters.py

  # Browser Chromium pulito (potrebbe essere bloccato da DataDome)
  python scraper_reuters.py --clean
""",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Usa un browser Chromium pulito invece del tuo Chrome",
    )
    args = parser.parse_args()

    html = fetch_page_html(use_clean=args.clean)
    articles = parse_articles(html)

    # ordina dal più recente al più vecchio
    articles.sort(key=lambda a: a["datetime"], reverse=True)

    # salva su file JSON
    OUTPUT_FILE.write_text(json.dumps(articles, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[✓] Salvati {len(articles)} articoli in {OUTPUT_FILE}")

    # stampa riepilogo
    print(f"\n{'─' * 90}")
    print(f"{'TITOLO':<60} {'NAZIONE':<15} {'ORA'}")
    print(f"{'─' * 90}")
    for a in articles:
        print(f"{a['title'][:58]:<60} {a['country']:<15} {a['time_ago']}")
    print(f"{'─' * 90}")
    print(f"Totale articoli (ultime 24h): {len(articles)}")


if __name__ == "__main__":
    main()
