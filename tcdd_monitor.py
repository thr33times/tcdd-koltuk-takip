#!/usr/bin/env python3
"""
TCDD seat availability monitor.

Route:
- İzmit YHT -> Ankara Gar
- 09.08.2026
- Departures at or after 17:02
- Economy and Business only
- Wheelchair/disabled-passenger quota is ignored

The selectors are based on the current TCDD e-ticket page structure and may
need updating if TCDD changes its HTML.
"""

from __future__ import annotations

import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


BASE_URL = "https://ebilet.tcddtasimacilik.gov.tr"
ORIGIN = os.getenv("TCDD_ORIGIN", "İZMİT YHT")
DESTINATION = os.getenv("TCDD_DESTINATION", "ANKARA GAR")
TRAVEL_DATE = os.getenv("TCDD_DATE", "09.08.2026")
MIN_DEPARTURE = os.getenv("TCDD_MIN_TIME", "17:02")
STATE_PATH = Path(os.getenv("STATE_PATH", "state.json"))
DEBUG_SCREENSHOT = Path("debug.png")
DEBUG_HTML = Path("debug.html")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TEST_NOTIFICATION = os.getenv("TEST_NOTIFICATION", "0") == "1"


def normalize_label(value: str) -> str:
    translation = str.maketrans(
        {
            "İ": "I",
            "Ş": "S",
            "Ğ": "G",
            "Ü": "U",
            "Ö": "O",
            "Ç": "C",
            "Â": "A",
        }
    )
    return (value or "").strip().upper().translate(translation)


def time_to_minutes(value: str) -> int:
    match = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", value or "")
    if not match:
        raise ValueError(f"Geçersiz saat: {value!r}")
    hour, minute = map(int, match.groups())
    return hour * 60 + minute


def parse_seat_count(value: str) -> int:
    # Examples expected from the site: "(0)", "(1)", "(12)"
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else 0


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(signature: str) -> None:
    STATE_PATH.write_text(
        json.dumps({"last_signature": signature}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID GitHub Secrets içinde eksik."
        )

    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        },
        timeout=25,
    )
    response.raise_for_status()


def click_first_visible(page: Page, selectors: list[str], timeout_ms: int = 2500) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.count() and locator.is_visible():
                locator.click(timeout=timeout_ms)
                return True
        except Exception:
            continue
    return False


def select_station(page: Page, input_selector: str, text: str, suggestion_prefix: str) -> None:
    field = page.locator(input_selector)
    field.wait_for(state="visible", timeout=20_000)
    field.click()
    field.fill(text)

    suggestion = page.locator(f'[id^="{suggestion_prefix}"]').first
    suggestion.wait_for(state="visible", timeout=10_000)
    suggestion.click()



def wait_for_loading_to_finish(page: Page, timeout_ms: int = 25_000) -> None:
    """
    Wait until TCDD's full-page loading overlay no longer blocks clicks.
    The overlay can remain active for several seconds after expanding a train.
    """
    try:
        page.wait_for_function(
            """() => {
                const overlays = Array.from(
                    document.querySelectorAll('.vld-overlay.is-active')
                );
                return overlays.length === 0 || overlays.every((element) => {
                    const style = window.getComputedStyle(element);
                    return style.display === 'none'
                        || style.visibility === 'hidden'
                        || style.opacity === '0';
                });
            }""",
            timeout=timeout_ms,
        )
    except PlaywrightTimeoutError:
        # Save a clearer error instead of allowing an unrelated click timeout.
        raise RuntimeError(
            "TCDD yükleme ekranı 25 saniye içinde kapanmadı."
        )


def click_train_card(page: Page, locator: Locator) -> None:
    """Click a train card only after the loading overlay has disappeared."""
    wait_for_loading_to_finish(page)
    locator.scroll_into_view_if_needed(timeout=10_000)

    try:
        locator.click(timeout=12_000)
    except PlaywrightTimeoutError:
        # One retry is useful when the site briefly redraws the card.
        wait_for_loading_to_finish(page)
        locator.click(timeout=12_000, force=True)

    wait_for_loading_to_finish(page)

def select_travel_date(page: Page, date_text: str) -> None:
    target = datetime.strptime(date_text, "%d.%m.%Y")
    today_tr = datetime.now(ZoneInfo("Europe/Istanbul")).date()
    if target.date() == today_tr:
        return

    opened = click_first_visible(
        page,
        [
            "#gidisTarih",
            "#departureDate",
            'input[class*="datepicker"]',
            'input[placeholder*="Tarih"]',
            'div[class*="daterange"]',
        ],
        timeout_ms=5000,
    )
    if not opened:
        raise RuntimeError("Tarih kutusu açılamadı.")

    day = str(target.day)
    day_padded = day.zfill(2)
    month = str(target.month).zfill(2)
    year = str(target.year)

    exact = page.locator(
        f'[id="{day_padded} {month} {year}"], [id="{day} {month} {year}"]'
    ).first

    try:
        exact.wait_for(state="visible", timeout=5000)
        exact.click()
        return
    except Exception:
        pass

    fallback = page.locator(
        f'xpath=//td[normalize-space()="{day}" '
        f'and not(contains(@class, "off")) '
        f'and not(contains(@class, "disabled"))]'
    ).first
    fallback.wait_for(state="visible", timeout=5000)
    fallback.click()


def get_train_rows(page: Page) -> list[int]:
    page.locator("#seferListScroll").wait_for(state="visible", timeout=30_000)
    page.wait_for_timeout(1500)

    ids = page.locator('[id^="gidis"][id$="btn"]').evaluate_all(
        "(els) => els.map(e => e.id)"
    )
    rows: list[int] = []
    for element_id in ids:
        match = re.fullmatch(r"gidis(\d+)btn", element_id or "")
        if match:
            rows.append(int(match.group(1)))
    return sorted(set(rows))


def text_or_empty(locator: Locator, timeout_ms: int = 3000) -> str:
    try:
        locator.wait_for(state="visible", timeout=timeout_ms)
        return locator.inner_text().strip()
    except Exception:
        return ""


def class_details_for_row(page: Page, row: int) -> dict[str, int]:
    """
    Reads only Economy/Business rows inside the expanded train card.
    The separate wheelchair icon/count on the collapsed card is never read.
    """
    found = {"EKONOMI": 0, "BUSINESS": 0}

    for index in range(1, 6):
        base = (
            "/html/body/div/main/section/div[2]/div/div[1]/div/div/section/"
            f"div[{row + 1}]/div[2]/div/div/div[1]/div/div[2]/div[2]/"
            f"div[2]/div/div[{index}]/button"
        )
        label = text_or_empty(page.locator(f"xpath={base}/div/div[1]/span"))
        if not label:
            continue

        normalized = normalize_label(label)
        if "EKONOM" in normalized:
            class_name = "EKONOMI"
        elif "BUSINESS" in normalized:
            class_name = "BUSINESS"
        else:
            # Wheelchair/other quota rows are deliberately ignored.
            continue

        count_text = text_or_empty(
            page.locator(f"xpath={base}/div/div[2]/div/div/span")
        )
        found[class_name] = parse_seat_count(count_text)

    return found


def inspect_trains(page: Page) -> list[dict[str, Any]]:
    rows = get_train_rows(page)
    minimum = time_to_minutes(MIN_DEPARTURE)
    available: list[dict[str, Any]] = []

    for row in rows:
        train_button = page.locator(f"#gidis{row}btn")
        departure_locator = train_button.locator("time").first
        departure = text_or_empty(departure_locator)

        if not departure:
            continue
        try:
            if time_to_minutes(departure) < minimum:
                continue
        except ValueError:
            continue

        card_text = text_or_empty(train_button)
        train_number_match = re.search(r"YHT\s*:\s*(\d+)", card_text, re.IGNORECASE)
        train_number = train_number_match.group(1) if train_number_match else "Bilinmiyor"

        print(
            f"Kontrol ediliyor: {departure} — YHT {train_number}",
            flush=True,
        )

        # Expand the train card. TCDD shows a full-page loading overlay while
        # fetching Economy/Business details, so wait for it before and after.
        try:
            click_train_card(page, departure_locator)
        except Exception:
            click_train_card(page, train_button)

        page.wait_for_timeout(400)
        class_counts = class_details_for_row(page, row)
        print(
            f"Sonuç: Ekonomi={class_counts['EKONOMI']}, "
            f"Business={class_counts['BUSINESS']}",
            flush=True,
        )

        for class_name, count in class_counts.items():
            if count > 0:
                available.append(
                    {
                        "train": train_number,
                        "departure": departure,
                        "class": "Ekonomi" if class_name == "EKONOMI" else "Business",
                        "count": count,
                    }
                )

        # Collapse before inspecting the next card when possible.
        try:
            click_train_card(page, train_button)
            page.wait_for_timeout(200)
        except Exception:
            # A failed collapse is harmless; the next click still waits for
            # the site's loading overlay to finish.
            wait_for_loading_to_finish(page)

    return available


def format_message(items: list[dict[str, Any]]) -> str:
    lines = [
        "🚄 TCDD koltuk bulundu!",
        f"{ORIGIN} → {DESTINATION}",
        f"Tarih: {TRAVEL_DATE}",
        "",
    ]

    grouped: dict[tuple[str, str], dict[str, int]] = {}

    for item in items:
        key = (item["departure"], item["train"])

        if key not in grouped:
            grouped[key] = {}

        grouped[key][item["class"]] = item["count"]

    for (departure, train), classes in grouped.items():
        seat_parts: list[str] = []

        if classes.get("Ekonomi", 0) > 0:
            seat_parts.append(f"Ekonomi: {classes['Ekonomi']}")

        if classes.get("Business", 0) > 0:
            seat_parts.append(f"Business: {classes['Business']}")

        lines.append(
            f"• {departure} — YHT {train} — {', '.join(seat_parts)}"
        )

    lines.extend(
        [
            "",
            "Tekerlekli sandalye kontenjanı bu bildirime dahil değildir.",
            "Bileti hemen TCDD E-Bilet uygulamasından kontrol et.",
        ]
    )

    return "\n".join(lines)


def main() -> int:
    if TEST_NOTIFICATION:
        send_telegram(
            "✅ TCDD takip botu test bildirimi çalıştı.\n"
            "İzmit YHT → Ankara Gar, 09.08.2026, 17:02 ve sonrası."
        )
        print("Test bildirimi gönderildi.")
        return 0

    target_date = datetime.strptime(TRAVEL_DATE, "%d.%m.%Y").date()
    today_tr = datetime.now(ZoneInfo("Europe/Istanbul")).date()
    if today_tr > target_date:
        print("Seyahat tarihi geçti; kontrol yapılmadı.")
        return 0

    available: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            locale="tr-TR",
            timezone_id="Europe/Istanbul",
            viewport={"width": 1600, "height": 1200},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/150.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(10_000)

        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
            page.locator("#fromTrainInput").wait_for(state="visible", timeout=30_000)

            click_first_visible(
                page,
                [
                    "xpath=/html/body/div[2]/div[1]/div/div/header/div/button",
                    'button[aria-label="Close"]',
                    'button:has-text("Kapat")',
                ],
            )

            select_station(page, "#fromTrainInput", ORIGIN, "gidis-")
            select_station(page, "#toTrainInput", DESTINATION, "donus-")
            select_travel_date(page, TRAVEL_DATE)

            page.locator("#searchSeferButton").click(timeout=10_000)
            available = inspect_trains(page)

        except Exception:
            try:
                page.screenshot(path=str(DEBUG_SCREENSHOT), full_page=True)
                DEBUG_HTML.write_text(page.content(), encoding="utf-8")
            except Exception:
                pass
            raise
        finally:
            context.close()
            browser.close()

    signature = "format-v2|" + json.dumps(
    available,
    ensure_ascii=False,
    sort_keys=True,
    )
    previous_signature = load_state().get("last_signature", "")

    if available and signature != previous_signature:
        send_telegram(format_message(available))
        print(f"Bildirim gönderildi: {len(available)} uygun sınıf/sefer.")
    elif available:
        print("Uygun koltuk hâlâ mevcut; aynı durum için tekrar bildirim gönderilmedi.")
    else:
        print("Ekonomi veya Business normal koltuk bulunamadı.")

    # Empty availability clears the signature, so a later reappearance triggers a new alert.
    save_state(signature if available else "")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1)
