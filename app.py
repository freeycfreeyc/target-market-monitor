# ============================================================
#  중고마켓 실시간 모니터링 프로그램  v4.5
#  ─────────────────────────────────────────
#  v4.5 수정:
#    - CARD_HEIGHT 74→100 (가격 잘림 방지)
#    - 가격 색상: C_ACCENT(핑크) → 흰색(#ffffff)
#    - 중고나라 색상: 파란색(#6c9cff) → 네온 그린(#03c75a)
# ============================================================

import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw
import requests
import threading
import time
import json
import os
import io
import re
import webbrowser
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager

# ============================================================
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

BUNJANG_API = "https://api.bunjang.co.kr/api/1/find_v2.json"
JOONGNA_WEB = "https://web.joongna.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://web.joongna.com/",
}

FAVORITES_FILE = "favorites.json"
SETTINGS_FILE  = "settings.json"
CHROME_PROFILE_DIR = os.path.join(os.getcwd(), "chrome_profile")

C_BG           = "#111111"
C_CARD         = "#1a1a1a"
C_SURFACE      = "#222222"
C_BORDER       = "#2a2a2a"
C_TEXT         = "#e0e0e0"
C_TEXT_DIM     = "#777777"
C_ACCENT       = "#ff4d6d"          # 번개장터 핑크
C_ACCENT_HOVER = "#d6385a"
C_TAG_BG       = "#2a2a2a"
C_TAG_TEXT     = "#cccccc"
C_BTN          = "#2a2a2a"
C_BTN_HOVER    = "#333333"
C_GREEN        = "#4ade80"
C_YELLOW       = "#facc15"
C_RED_DIM      = "#ef4444"
C_GLOW_PEAK    = "#2e1620"

# ★ v4.5 변경: 가격 색상 + 중고나라 색상
C_PRICE        = "#ffffff"           # 가격: 흰색
C_JOONGNA      = "#03c75a"           # 중고나라: 네이버 네온 그린


# ============================================================
#  유틸리티
# ============================================================
def load_json(path, default=None):
    if default is None:
        default = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def time_ago(ts):
    try:
        if not ts:
            return ""
        if isinstance(ts, str):
            ts = ts.strip()
            if any(k in ts for k in ("전", "방금", "초", "분", "시간", "일")):
                return ts
            ts_clean = ts.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(ts_clean)
            except Exception:
                try:
                    numeric = int(float(ts))
                    if numeric > 1e12:
                        numeric = numeric // 1000
                    dt = datetime.fromtimestamp(numeric, tz=timezone.utc)
                except Exception:
                    return ""
            if dt.tzinfo:
                diff = datetime.now(timezone.utc) - dt
            else:
                diff = datetime.now() - dt
        elif isinstance(ts, (int, float)):
            numeric = int(ts)
            if numeric > 1e12:
                numeric = numeric // 1000
            diff = datetime.now(timezone.utc) - datetime.fromtimestamp(
                numeric, tz=timezone.utc)
        else:
            return ""
        secs = max(0, int(diff.total_seconds()))
        if secs < 60:
            return "방금 전"
        elif secs < 3600:
            return f"{secs // 60}분 전"
        elif secs < 86400:
            return f"{secs // 3600}시간 전"
        else:
            return f"{secs // 86400}일 전"
    except Exception:
        return ""


def format_price(price):
    if price is None:
        return ""
    if isinstance(price, (int, float)):
        p = int(price)
        if p == 0:
            return "나눔"
        return f"{p:,}원"
    s = str(price).strip()
    if not s:
        return ""
    # "만원" 처리
    m = re.match(r'(\d+)\s*만\s*원', s)
    if m:
        p = int(m.group(1)) * 10000
        return f"{p:,}원"
    digits = re.sub(r'[^\d]', '', s)
    if not digits:
        return ""
    p = int(digits)
    if p == 0:
        return "나눔"
    return f"{p:,}원"


def clean_title(raw_title):
    if not raw_title:
        return ""
    cleaned = raw_title.strip()
    cleaned = re.sub(
        r'\s*(대표\s*)?이미지$|\s*사진$|\s*썸네일$|\s*image$',
        '', cleaned, flags=re.IGNORECASE
    ).strip()
    return cleaned


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def rgb_to_hex(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def lerp_color(c1, c2, t):
    r1, g1, b1 = hex_to_rgb(c1)
    r2, g2, b2 = hex_to_rgb(c2)
    return rgb_to_hex(
        r1 + (r2 - r1) * t,
        g1 + (g2 - g1) * t,
        b1 + (b2 - b1) * t,
    )


# ============================================================
#  ChromeManager
# ============================================================
class ChromeManager:
    def __init__(self, profile_dir):
        self.profile_dir = profile_dir
        self.driver = None
        self._lock = threading.Lock()
        self._mode = None

    def _base_options(self):
        opts = Options()
        opts.add_argument(f"--user-data-dir={self.profile_dir}")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--window-size=1280,900")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-popup-blocking")
        return opts

    def _create_driver(self, headless):
        opts = self._base_options()
        if headless:
            opts.add_argument("--headless=new")
            self._mode = "headless"
        else:
            self._mode = "visible"
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=opts)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"},
        )
        return driver

    def start_headless(self):
        with self._lock:
            self._close_internal()
            self.driver = self._create_driver(headless=True)

    def switch_to_visible(self):
        with self._lock:
            self._close_internal()
            self.driver = self._create_driver(headless=False)

    def switch_to_headless(self):
        with self._lock:
            self._close_internal()
            self.driver = self._create_driver(headless=True)

    def get(self, url, timeout=20):
        with self._lock:
            if not self.driver:
                raise RuntimeError("Driver not started")
            self.driver.set_page_load_timeout(timeout)
            self.driver.get(url)

    def page_source(self):
        with self._lock:
            return self.driver.page_source if self.driver else ""

    def execute_script(self, script, *args):
        with self._lock:
            return self.driver.execute_script(script, *args) if self.driver else None

    def current_url(self):
        with self._lock:
            return self.driver.current_url if self.driver else ""

    @property
    def is_alive(self):
        try:
            with self._lock:
                if not self.driver:
                    return False
                self.driver.title
                return True
        except Exception:
            return False

    @property
    def mode(self):
        return self._mode

    def quit(self):
        with self._lock:
            self._close_internal()

    def _close_internal(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            self._mode = None


# ============================================================
#  번개장터 크롤러
# ============================================================
class BunjangCrawler:
    @staticmethod
    def search(keyword, limit=20):
        items = []
        try:
            params = {"q": keyword, "order": "date", "page": 0, "n": limit}
            resp = requests.get(BUNJANG_API, params=params, headers=HEADERS, timeout=10)
            data = resp.json()
            for item in data.get("list", []):
                raw_price = item.get("price")
                price_str = format_price(raw_price)
                items.append({
                    "id": f"bj_{item.get('pid', '')}",
                    "title": clean_title(item.get("name", "")),
                    "price": price_str,
                    "image": item.get("product_image", ""),
                    "time": time_ago(item.get("update_time", "")),
                    "url": f"https://m.bunjang.co.kr/products/{item.get('pid', '')}",
                    "source": "번개장터",
                })
        except Exception as e:
            print(f"[번개장터 오류] {e}")
        return items


# ============================================================
#  중고나라 크롤러  (v4.4+)
# ============================================================
class JoongnaCrawler:
    def __init__(self, chrome_manager):
        self.cm = chrome_manager

    def search(self, keyword, limit=20):
        items = []
        try:
            url = f"{JOONGNA_WEB}/search?keyword={quote(keyword)}"
            self.cm.get(url, timeout=25)
            time.sleep(3)

            items = self._parse_next_data(limit)
            if items:
                print(f"[중고나라] __NEXT_DATA__ 파싱 성공: {len(items)}건")
                return items

            items = self._parse_via_js(limit)
            if items:
                print(f"[중고나라] JS __NEXT_DATA__ 파싱 성공: {len(items)}건")
                return items

            items = self._parse_via_dom_js(limit)
            if items:
                print(f"[중고나라] DOM JS 파싱 성공: {len(items)}건")
                return items

            items = self._parse_dom_regex(limit)
            if items:
                print(f"[중고나라] DOM Regex 파싱 성공: {len(items)}건")
        except Exception as e:
            print(f"[중고나라 오류] {e}")
        return items

    def _extract_item(self, p):
        title = ""
        for key in ("title", "name", "productTitle", "subject", "productName"):
            val = p.get(key)
            if val and isinstance(val, str) and val.strip():
                title = clean_title(val)
                break

        price = ""
        for key in ("price", "productPrice", "salePrice", "wishPrice",
                     "sellPrice", "amount", "payPrice", "displayPrice"):
            val = p.get(key)
            if val is not None:
                formatted = format_price(val)
                if formatted:
                    price = formatted
                    break
        if not price:
            for key in ("priceInfo", "priceData"):
                val = p.get(key)
                if isinstance(val, dict):
                    for sub in ("price", "sellPrice", "amount", "displayPrice"):
                        sv = val.get(sub)
                        if sv is not None:
                            formatted = format_price(sv)
                            if formatted:
                                price = formatted
                                break
                    if price:
                        break

        img = ""
        for key in ("imageUrl", "image", "imageURL", "thumbnailUrl",
                     "thumbnail", "mainImage", "photo", "photoUrl",
                     "imageUri", "mainImageUrl", "thumbImageUrl"):
            val = p.get(key)
            if val and isinstance(val, str) and (val.startswith("http") or val.startswith("//")):
                img = val
                break
        if not img:
            for key in ("imageUrls", "images", "photos", "thumbnails", "imageList", "productImages"):
                val = p.get(key)
                if val and isinstance(val, list) and len(val) > 0:
                    first = val[0]
                    if isinstance(first, str):
                        img = first
                    elif isinstance(first, dict):
                        img = first.get("url", first.get("imageUrl", first.get("uri", "")))
                    break
        if img and not img.startswith("http"):
            img = ("https:" + img) if img.startswith("//") else ""

        time_raw = ""
        for key in ("sortDate", "updatedAt", "regDate", "createdAt",
                     "registeredAt", "modifiedAt", "updateTime",
                     "regDatetime", "modDate", "postedAt", "insertDt"):
            val = p.get(key)
            if val:
                time_raw = val
                break

        pid = ""
        for key in ("seq", "productSeq", "productId", "id", "pid", "productNo", "num"):
            val = p.get(key)
            if val is not None and str(val).strip():
                pid = str(val)
                break

        return {
            "id": f"jn_{pid}" if pid else "",
            "title": title,
            "price": price,
            "image": img,
            "time": time_ago(time_raw),
            "url": f"{JOONGNA_WEB}/product/{pid}" if pid else "",
            "source": "중고나라",
        }

    def _parse_next_data(self, limit):
        items = []
        try:
            src = self.cm.page_source()
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', src, re.DOTALL)
            if not m:
                return []
            nd = json.loads(m.group(1))
            products = self._find_products(nd)
            for p in products[:limit]:
                item = self._extract_item(p)
                if item["id"] and item["title"]:
                    items.append(item)
        except Exception as e:
            print(f"[__NEXT_DATA__] {e}")
        return items

    def _parse_via_js(self, limit):
        items = []
        try:
            data = self.cm.execute_script(
                "try{return JSON.parse(document.querySelector('#__NEXT_DATA__')?.textContent||'{}')}catch(e){return {}}")
            if not data or not isinstance(data, dict):
                return []
            products = self._find_products(data)
            for p in products[:limit]:
                item = self._extract_item(p)
                if item["id"] and item["title"]:
                    items.append(item)
        except Exception as e:
            print(f"[JS __NEXT_DATA__] {e}")
        return items

    def _parse_via_dom_js(self, limit):
        items = []
        try:
            script = """
            var results = [];
            var links = document.querySelectorAll('a[href*="/product/"]');
            
            links.forEach(function(a) {
                var href = a.getAttribute('href') || '';
                var match = href.match(/\\/product\\/(\\d+)/);
                if (!match) return;
                var pid = match[1];
                
                var imgEl = a.querySelector('img');
                var imgUrl = imgEl ? (imgEl.getAttribute('src') || '') : '';
                
                var allText = a.innerText || a.textContent || '';
                var lines = allText.split('\\n').map(function(s){ return s.trim(); })
                                   .filter(function(s){ return s.length > 0; });
                
                var title = '';
                var price = '';
                var timeStr = '';
                
                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i];
                    
                    if (!price) {
                        if (/[\\d,]+\\s*원/.test(line)) {
                            price = line;
                            continue;
                        }
                        if (/\\d+\\s*만\\s*원/.test(line)) {
                            price = line;
                            continue;
                        }
                        if (/^[\\d,]+$/.test(line) && line.length >= 3 && parseInt(line.replace(/,/g,'')) > 0) {
                            price = line + '원';
                            continue;
                        }
                        if (/무료|나눔/.test(line)) {
                            price = '나눔';
                            continue;
                        }
                    }
                    
                    if (!timeStr && /(전|방금|초 전|분 전|시간 전|일 전)/.test(line) && line.length < 20) {
                        timeStr = line;
                        continue;
                    }
                    
                    if (!title && line.length >= 2 
                        && !/^(판매중|예약중|거래완료|광고|AD|NEW|N)$/i.test(line)
                        && !/^[\\d,]+$/.test(line)) {
                        title = line;
                        continue;
                    }
                }
                
                if (!price) {
                    var allSpans = a.querySelectorAll('span, p, div, em, strong');
                    for (var j = 0; j < allSpans.length; j++) {
                        var st = (allSpans[j].innerText || allSpans[j].textContent || '').trim();
                        if (/[\\d,]+\\s*원/.test(st) && st.length < 30) {
                            price = st.match(/[\\d,]+\\s*원/)[0];
                            break;
                        }
                        if (/^[\\d,]+$/.test(st) && st.length >= 3) {
                            var num = parseInt(st.replace(/,/g,''));
                            if (num > 0) {
                                price = num.toLocaleString() + '원';
                                break;
                            }
                        }
                    }
                }
                
                if (pid && title) {
                    results.push({
                        id: pid,
                        title: title,
                        price: price || '',
                        time: timeStr || '',
                        image: imgUrl
                    });
                }
            });
            return results.slice(0, """ + str(limit) + """);
            """
            raw = self.cm.execute_script(script)
            if not raw or not isinstance(raw, list):
                return []

            for r in raw:
                pid = str(r.get("id", ""))
                title = clean_title(r.get("title", ""))
                raw_price = r.get("price", "")
                price = format_price(raw_price) if raw_price else ""
                img = r.get("image", "")
                if img and not img.startswith("http"):
                    img = ("https:" + img) if img.startswith("//") else ""
                time_str = r.get("time", "")

                if pid and title:
                    items.append({
                        "id": f"jn_{pid}",
                        "title": title,
                        "price": price,
                        "image": img,
                        "time": time_str,
                        "url": f"{JOONGNA_WEB}/product/{pid}",
                        "source": "중고나라",
                    })
        except Exception as e:
            print(f"[DOM JS] {e}")
        return items

    def _parse_dom_regex(self, limit):
        items = []
        try:
            src = self.cm.page_source()
            pat = re.compile(r'<a[^>]*href="(/product/(\d+))"[^>]*>(.*?)</a>', re.DOTALL)
            for m in pat.finditer(src):
                if len(items) >= limit:
                    break
                pid = m.group(2)
                html = m.group(3)
                title = ""
                am = re.search(r'alt="([^"]*)"', html)
                if am:
                    title = clean_title(am.group(1))
                if not title:
                    tm = re.search(r'>([^<]{2,})<', html)
                    if tm:
                        title = clean_title(tm.group(1).strip())
                img = ""
                im = re.search(r'src="(https?://[^"]+)"', html)
                if im:
                    img = im.group(1)
                price = ""
                pm = re.search(r'([\d,]+)\s*원', html)
                if pm:
                    price = format_price(pm.group(1))
                time_str = ""
                tm2 = re.search(r'(\d+\s*(?:초|분|시간|일)\s*전|방금\s*전)', html)
                if tm2:
                    time_str = tm2.group(1)
                if pid and title:
                    items.append({
                        "id": f"jn_{pid}",
                        "title": title,
                        "price": price,
                        "image": img,
                        "time": time_str,
                        "url": f"{JOONGNA_WEB}/product/{pid}",
                        "source": "중고나라",
                    })
        except Exception as e:
            print(f"[DOM Regex] {e}")
        return items

    @staticmethod
    def _find_products(obj, _depth=0):
        if _depth > 20:
            return []
        if isinstance(obj, list) and len(obj) > 0:
            first = obj[0] if isinstance(obj[0], dict) else None
            if first:
                title_keys = ("title", "name", "productTitle", "subject", "productName")
                id_keys = ("seq", "productSeq", "id", "pid", "productId", "productNo", "num")
                price_keys = ("price", "productPrice", "salePrice", "wishPrice", "sellPrice", "amount")
                img_keys = ("imageUrl", "image", "thumbnailUrl", "thumbnail", "mainImage")
                has_t = any(k in first for k in title_keys)
                has_i = any(k in first for k in id_keys)
                has_p = any(k in first for k in price_keys)
                has_img = any(k in first for k in img_keys)
                if has_t and has_i:
                    return obj
                if has_i and (has_p or has_img):
                    return obj
        if isinstance(obj, dict):
            priority = ("data", "items", "list", "products", "result",
                        "content", "pageProps", "dehydratedState",
                        "queries", "state", "searchList", "productList",
                        "searchProducts", "searchResult", "results")
            for key in priority:
                if key in obj:
                    r = JoongnaCrawler._find_products(obj[key], _depth + 1)
                    if r:
                        return r
            for k, v in obj.items():
                if k not in priority:
                    r = JoongnaCrawler._find_products(v, _depth + 1)
                    if r:
                        return r
        if isinstance(obj, list):
            for item in obj:
                r = JoongnaCrawler._find_products(item, _depth + 1)
                if r:
                    return r
        return []


# ============================================================
#  카드 글로우 애니메이터
# ============================================================
class CardAnimator:
    GLOW_DURATION_MS = 900
    GLOW_STEPS       = 20

    @staticmethod
    def glow(app, card):
        half = CardAnimator.GLOW_STEPS // 2
        delay = CardAnimator.GLOW_DURATION_MS // CardAnimator.GLOW_STEPS

        def step(i):
            if i > CardAnimator.GLOW_STEPS:
                try:
                    card.configure(fg_color=C_CARD)
                except Exception:
                    pass
                return
            t = i / half if i <= half else 1.0 - (i - half) / half
            color = lerp_color(C_CARD, C_GLOW_PEAK, t)
            try:
                card.configure(fg_color=color)
            except Exception:
                return
            app.after(delay, lambda: step(i + 1))
        step(0)

    @staticmethod
    def glow_batch(app, cards, stagger_ms=120):
        for idx, card in enumerate(cards):
            app.after(idx * stagger_ms, lambda c=card: CardAnimator.glow(app, c))


# ============================================================
#  메인 앱
# ============================================================
class MarketMonitorApp(ctk.CTk):

    CARD_IMG_SIZE = 56
    CARD_PAD_X    = 8
    CARD_PAD_Y    = 6
    CARD_GAP      = 3
    CARD_HEIGHT   = 100        # ★ v4.5: 74→100 (가격 잘림 방지)

    def __init__(self):
        super().__init__()
        self.title("HAMON")
        self.geometry("500x800")
        self.minsize(460, 650)
        self.configure(fg_color=C_BG)

        self.keywords   = []
        self.favorites  = load_json(FAVORITES_FILE, [])
        self.settings   = load_json(SETTINGS_FILE, {"interval": 30})
        self.monitoring = False

        self._monitor_thread  = None
        self._seen_ids        = set()
        self._image_cache     = {}
        self._card_widgets    = []
        self._card_heart_btns = {}
        self._card_items      = {}
        self._spinner_running = False
        self._spinner_idx     = 0
        self._spinner_chars   = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]

        self.chrome_mgr       = ChromeManager(CHROME_PROFILE_DIR)
        self.joongna_crawler  = JoongnaCrawler(self.chrome_mgr)
        self._chrome_ready    = False

        self._build_header()
        self._build_keyword_area()
        self._build_controls()
        self._build_results_area()
        self._build_status_bar()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─────────────── UI 빌드 ───────────────

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=0, height=50)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="  HAMON",
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=C_TEXT).pack(side="left", padx=(12, 0), pady=10)
        ctk.CTkLabel(header, text="Hot Asset Monitor for 번개장터 & 중고나라",
                     font=ctk.CTkFont(size=12),
                     text_color=C_TEXT_DIM).pack(side="left", padx=(6, 0), pady=(13, 10))

        self.fav_btn = ctk.CTkButton(
            header, text="♥ 즐겨찾기", width=80, height=30,
            fg_color=C_BTN, hover_color=C_BTN_HOVER,
            text_color=C_TEXT_DIM, font=ctk.CTkFont(size=12),
            command=self._show_favorites, corner_radius=6, border_width=0)
        self.fav_btn.pack(side="right", padx=8)
        ctk.CTkButton(header, text="⚙", width=30, height=30,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      text_color=C_TEXT_DIM, font=ctk.CTkFont(size=15),
                      command=self._show_settings,
                      corner_radius=6, border_width=0).pack(side="right", padx=(0, 2))

    def _build_keyword_area(self):
        kw_frame = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=10)
        kw_frame.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(kw_frame, text="검색 키워드",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=C_TEXT_DIM).pack(anchor="w", padx=12, pady=(10, 4))
        input_row = ctk.CTkFrame(kw_frame, fg_color="transparent")
        input_row.pack(fill="x", padx=10, pady=(0, 4))
        self.kw_entry = ctk.CTkEntry(
            input_row, placeholder_text="키워드 입력 후 Enter",
            height=34, fg_color=C_SURFACE, border_color=C_BORDER,
            text_color=C_TEXT, font=ctk.CTkFont(size=13),
            border_width=1, corner_radius=6)
        self.kw_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.kw_entry.bind("<Return>", lambda e: self._add_keyword())
        ctk.CTkButton(input_row, text="추가", width=50, height=34,
                      fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER,
                      text_color="white",
                      font=ctk.CTkFont(size=12, weight="bold"),
                      command=self._add_keyword,
                      corner_radius=6, border_width=0).pack(side="right")
        self.tag_frame = ctk.CTkFrame(kw_frame, fg_color="transparent")
        self.tag_frame.pack(fill="x", padx=10, pady=(0, 8))

    def _add_keyword(self):
        kw = self.kw_entry.get().strip()
        if not kw or kw in self.keywords:
            return
        self.keywords.append(kw)
        self.kw_entry.delete(0, "end")
        self._refresh_tags()

    def _remove_keyword(self, kw):
        if kw in self.keywords:
            self.keywords.remove(kw)
        self._refresh_tags()

    def _refresh_tags(self):
        for w in self.tag_frame.winfo_children():
            w.destroy()
        for kw in self.keywords:
            tag = ctk.CTkFrame(self.tag_frame, fg_color=C_TAG_BG, corner_radius=14)
            tag.pack(side="left", padx=3, pady=3)
            ctk.CTkLabel(tag, text=f" {kw} ", text_color=C_TAG_TEXT,
                         font=ctk.CTkFont(size=12)).pack(side="left", padx=(8, 0), pady=3)
            ctk.CTkButton(tag, text="✕", width=22, height=22,
                          fg_color="transparent", hover_color="#444444",
                          text_color=C_TEXT_DIM, font=ctk.CTkFont(size=10),
                          command=lambda k=kw: self._remove_keyword(k),
                          corner_radius=11, border_width=0).pack(side="right", padx=(0, 4), pady=3)

    def _build_controls(self):
        ctrl = ctk.CTkFrame(self, fg_color="transparent")
        ctrl.pack(fill="x", padx=10, pady=4)
        self.connect_btn = ctk.CTkButton(
            ctrl, text="연결", width=70, height=34,
            fg_color=C_BTN, hover_color=C_BTN_HOVER, text_color=C_TEXT,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._toggle_connection, corner_radius=6, border_width=0)
        self.connect_btn.pack(side="left", padx=(0, 6))
        self.start_btn = ctk.CTkButton(
            ctrl, text="▶  모니터링 시작", height=36,
            fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER, text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._toggle_monitoring, corner_radius=6, border_width=0)
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ctk.CTkButton(ctrl, text="🗑", width=36, height=36,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      text_color=C_TEXT_DIM, font=ctk.CTkFont(size=14),
                      command=self._clear_all_cards,
                      corner_radius=6, border_width=0).pack(side="right")

    def _build_results_area(self):
        container = ctk.CTkFrame(self, fg_color=C_BG, corner_radius=0)
        container.pack(fill="both", expand=True, padx=10, pady=4)
        self.scroll_frame = ctk.CTkScrollableFrame(
            container, fg_color=C_BG,
            scrollbar_button_color=C_BORDER,
            scrollbar_button_hover_color=C_TEXT_DIM)
        self.scroll_frame.pack(fill="both", expand=True)
        self.empty_label = ctk.CTkLabel(
            self.scroll_frame,
            text="키워드를 추가하고 모니터링을 시작하세요",
            font=ctk.CTkFont(size=13), text_color=C_TEXT_DIM)
        self.empty_label.pack(pady=80)

    def _build_status_bar(self):
        bar = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=0, height=28)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)
        self.status_label = ctk.CTkLabel(bar, text="대기 중",
                                          font=ctk.CTkFont(size=11), text_color=C_TEXT_DIM)
        self.status_label.pack(side="left", padx=10)
        self.chrome_status = ctk.CTkLabel(bar, text="● 미연결",
                                           font=ctk.CTkFont(size=11), text_color=C_TEXT_DIM)
        self.chrome_status.pack(side="right", padx=10)

    # ─────────────── 매물 초기화 ───────────────

    def _clear_all_cards(self):
        for card in self._card_widgets:
            try:
                card.destroy()
            except Exception:
                pass
        self._card_widgets.clear()
        self._card_heart_btns.clear()
        self._card_items.clear()
        self._seen_ids.clear()
        self.empty_label = ctk.CTkLabel(
            self.scroll_frame,
            text="키워드를 추가하고 모니터링을 시작하세요",
            font=ctk.CTkFont(size=13), text_color=C_TEXT_DIM)
        self.empty_label.pack(pady=80)
        self._set_status("매물 초기화 완료")

    # ─────────────── Chrome 연결 ───────────────

    def _toggle_connection(self):
        if self._chrome_ready:
            self._disconnect_chrome()
        else:
            self._connect_chrome()

    def _connect_chrome(self):
        self.connect_btn.configure(state="disabled", text="연결 중…")
        self.chrome_status.configure(text="● 연결 중…", text_color=C_YELLOW)
        threading.Thread(target=self._do_connect, daemon=True).start()

    def _do_connect(self):
        try:
            self.chrome_mgr.start_headless()
            self.chrome_mgr.get(JOONGNA_WEB, timeout=20)
            time.sleep(2)
            cur_url = self.chrome_mgr.current_url().lower()
            if "login" in cur_url:
                self.after(0, lambda: self._set_status("로그인 필요 — 크롬 창에서 로그인하세요"))
                self.after(0, lambda: self.chrome_status.configure(text="● 로그인 필요", text_color=C_YELLOW))
                self.chrome_mgr.switch_to_visible()
                self.chrome_mgr.get("https://web.joongna.com/login", timeout=20)
                waited = 0
                while waited < 120:
                    time.sleep(3)
                    waited += 3
                    cur = self.chrome_mgr.current_url().lower()
                    if "login" not in cur:
                        break
                self.after(0, lambda: self._set_status("로그인 완료, 헤드리스로 전환 중…"))
                time.sleep(1)
                self.chrome_mgr.switch_to_headless()
                time.sleep(1)
            self._chrome_ready = True
            self.after(0, self._on_connect_success)
        except Exception as e:
            self._chrome_ready = False
            self.after(0, lambda: self._on_connect_fail(str(e)))

    def _on_connect_success(self):
        self.connect_btn.configure(state="normal", text="연결 해제",
                                    fg_color=C_BTN, hover_color=C_BTN_HOVER)
        self.chrome_status.configure(text="● 연결됨", text_color=C_GREEN)
        self._set_status("중고나라 연결 완료 (백그라운드)")

    def _on_connect_fail(self, err):
        self.connect_btn.configure(state="normal", text="연결")
        self.chrome_status.configure(text="● 연결 실패", text_color=C_RED_DIM)
        self._set_status(f"연결 실패: {err[:50]}")

    def _disconnect_chrome(self):
        self.chrome_mgr.quit()
        self._chrome_ready = False
        self.connect_btn.configure(text="연결", fg_color=C_BTN, hover_color=C_BTN_HOVER)
        self.chrome_status.configure(text="● 미연결", text_color=C_TEXT_DIM)
        self._set_status("연결 해제됨")

    # ─────────────── 모니터링 ───────────────

    def _toggle_monitoring(self):
        if self.monitoring:
            self._stop_monitoring()
        else:
            self._start_monitoring()

    def _start_monitoring(self):
        if not self.keywords:
            self._set_status("키워드를 먼저 추가하세요")
            return
        self.monitoring = True
        self.start_btn.configure(text="■  모니터링 중지",
                                  fg_color="#333333", hover_color="#444444")
        self._start_spinner()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _stop_monitoring(self):
        self.monitoring = False
        self.start_btn.configure(text="▶  모니터링 시작",
                                  fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER)
        self._stop_spinner()
        self._set_status("모니터링 중지")

    def _monitor_loop(self):
        while self.monitoring:
            self._do_search()
            interval = self.settings.get("interval", 30)
            for _ in range(interval):
                if not self.monitoring:
                    return
                time.sleep(1)

    def _do_search(self):
        all_items = []
        for kw in list(self.keywords):
            self.after(0, lambda k=kw: self._set_status(f"검색 중: {k}"))
            try:
                bj = BunjangCrawler.search(kw, limit=10)
                all_items.extend(bj)
                print(f"[번개장터] '{kw}': {len(bj)}건")
            except Exception as e:
                print(f"[번개장터] {e}")

            if self._chrome_ready:
                try:
                    jn = self.joongna_crawler.search(kw, limit=10)
                    all_items.extend(jn)
                    print(f"[중고나라] '{kw}': {len(jn)}건")
                    if jn:
                        print(f"  첫 결과: {jn[0]}")
                except Exception as e:
                    print(f"[중고나라] {e}")
                    if not self.chrome_mgr.is_alive:
                        self._chrome_ready = False
                        self.after(0, lambda: self.chrome_status.configure(
                            text="● 연결 끊김", text_color=C_RED_DIM))
            time.sleep(0.5)

        is_first = len(self._seen_ids) == 0
        new_items = []
        for i in all_items:
            if i["id"] and i["id"] not in self._seen_ids:
                self._seen_ids.add(i["id"])
                new_items.append(i)

        now = datetime.now().strftime("%H:%M:%S")
        if new_items:
            self.after(0, lambda items=new_items, first=is_first:
                       self._display_new_items(items, animate=not first))
            self.after(0, lambda: self._set_status(
                f"{len(new_items)}개 새 상품  ({now})"))
        else:
            self.after(0, lambda: self._set_status(f"새 상품 없음  ({now})"))

    # ────────────────────────────────────────────
    #  카드 표시  (Full Repack)
    # ────────────────────────────────────────────

    def _display_new_items(self, items, animate=True):
        try:
            if hasattr(self, "empty_label") and self.empty_label.winfo_exists():
                self.empty_label.destroy()
        except Exception:
            pass

        for card in self._card_widgets:
            try:
                card.pack_forget()
            except Exception:
                pass

        created = []
        for item in items:
            card = self._create_card(item)
            created.append(card)

        self._card_widgets = created + self._card_widgets

        for card in self._card_widgets:
            card.pack(fill="x", pady=(0, self.CARD_GAP), padx=2)

        if animate and created:
            CardAnimator.glow_batch(self, created, stagger_ms=120)

        self.after(50, self._scroll_to_top)

    def _scroll_to_top(self):
        try:
            self.scroll_frame._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass

    def _create_card(self, item):
        card = ctk.CTkFrame(
            self.scroll_frame, fg_color=C_CARD,
            corner_radius=8, height=self.CARD_HEIGHT)
        card.pack_propagate(False)

        # ── 이미지 ──
        sz = self.CARD_IMG_SIZE
        img_label = ctk.CTkLabel(card, text="", width=sz, height=sz,
                                  fg_color=C_SURFACE, corner_radius=6)
        img_label.pack(side="left", padx=(self.CARD_PAD_X, 6), pady=self.CARD_PAD_Y)

        if item.get("image"):
            threading.Thread(target=self._load_image,
                             args=(item["image"], img_label, sz), daemon=True).start()

        # ── 하트 (오른쪽 끝) ──
        is_fav = any(f.get("id") == item["id"] for f in self.favorites)
        heart_btn = ctk.CTkButton(
            card,
            text="♥" if is_fav else "♡",
            width=30, height=30,
            fg_color="transparent", hover_color=C_BTN_HOVER,
            text_color=C_ACCENT if is_fav else C_TEXT_DIM,
            font=ctk.CTkFont(size=16),
            command=None,
            corner_radius=6, border_width=0)
        heart_btn.pack(side="right", padx=(0, self.CARD_PAD_X), pady=self.CARD_PAD_Y)

        # ── 텍스트 영역 ──
        text_frame = ctk.CTkFrame(card, fg_color="transparent")
        text_frame.pack(side="left", fill="both", expand=True, pady=(5, 5))

        # 출처 + 시간
        top_row = ctk.CTkFrame(text_frame, fg_color="transparent")
        top_row.pack(anchor="w", fill="x")

        # ★ v4.5: 중고나라 → 네온 그린
        source_color = C_ACCENT if item["source"] == "번개장터" else C_JOONGNA
        ctk.CTkLabel(top_row, text=item["source"],
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=source_color).pack(side="left")
        time_text = item.get("time", "")
        if time_text:
            ctk.CTkLabel(top_row, text=f"  ·  {time_text}",
                         font=ctk.CTkFont(size=10),
                         text_color=C_TEXT_DIM).pack(side="left")

        # 제목
        title_text = item.get("title", "").strip() or "(제목 없음)"
        if len(title_text) > 35:
            title_text = title_text[:35] + "…"
        ctk.CTkLabel(text_frame, text=title_text,
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C_TEXT, anchor="w").pack(anchor="w", pady=(2, 0))

        # ★ v4.5: 가격 — 흰색
        price_text = item.get("price", "").strip()
        if price_text:
            ctk.CTkLabel(text_frame, text=price_text,
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=C_PRICE, anchor="w").pack(anchor="w", pady=(2, 0))
        else:
            ctk.CTkLabel(text_frame, text="가격 정보 없음",
                         font=ctk.CTkFont(size=10),
                         text_color=C_TEXT_DIM, anchor="w").pack(anchor="w", pady=(1, 0))

        # ── 매핑 + 커맨드 ──
        heart_btn.configure(command=lambda c=card, i=item: self._toggle_favorite(c, i))
        self._card_heart_btns[id(card)] = heart_btn
        self._card_items[id(card)] = item

        # ── 카드 클릭 → URL ──
        url = item.get("url", "")
        if url:
            self._bind_recursive(card, "<Button-1>",
                                  lambda e, u=url: webbrowser.open(u),
                                  exclude=heart_btn)
        return card

    # ─────────────── 공용 ───────────────

    def _bind_recursive(self, widget, event, callback, exclude=None):
        if widget is exclude:
            return
        widget.bind(event, callback)
        for child in widget.winfo_children():
            self._bind_recursive(child, event, callback, exclude=exclude)

    def _load_image(self, url, label, size=56):
        try:
            if url in self._image_cache:
                photo = self._image_cache[url]
            else:
                resp = requests.get(url, headers=HEADERS, timeout=8)
                if resp.status_code != 200:
                    return
                img = Image.open(io.BytesIO(resp.content))
                img = img.resize((size, size), Image.LANCZOS)
                mask = Image.new("L", (size, size), 0)
                draw = ImageDraw.Draw(mask)
                draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=6, fill=255)
                output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                output.paste(img.convert("RGBA"), mask=mask)
                photo = ctk.CTkImage(light_image=output, dark_image=output, size=(size, size))
                self._image_cache[url] = photo
            self.after(0, lambda: label.configure(image=photo, text=""))
        except Exception as e:
            print(f"[이미지] {e}")

    # ─────────────── 즐겨찾기 ───────────────

    def _toggle_favorite(self, card, item):
        item_id = item["id"]
        exists = [i for i, f in enumerate(self.favorites) if f.get("id") == item_id]
        heart_btn = self._card_heart_btns.get(id(card)) if card else None

        if exists:
            for idx in sorted(exists, reverse=True):
                self.favorites.pop(idx)
            if heart_btn:
                heart_btn.configure(text="♡", text_color=C_TEXT_DIM)
            self._set_status(f"즐겨찾기 해제: {item.get('title','')[:20]}")
        else:
            self.favorites.append(item)
            if heart_btn:
                heart_btn.configure(text="♥", text_color=C_ACCENT)
            self._set_status(f"즐겨찾기 추가: {item.get('title','')[:20]}")

        save_json(FAVORITES_FILE, self.favorites)

    def _show_favorites(self):
        win = ctk.CTkToplevel(self)
        win.title("즐겨찾기")
        win.geometry("460x520")
        win.configure(fg_color=C_BG)
        win.transient(self)
        win.grab_set()

        header_row = ctk.CTkFrame(win, fg_color="transparent")
        header_row.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(header_row, text="♥ 즐겨찾기",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=C_TEXT).pack(side="left")
        count_label = ctk.CTkLabel(header_row, text=f"{len(self.favorites)}개",
                     font=ctk.CTkFont(size=12),
                     text_color=C_TEXT_DIM)
        count_label.pack(side="right")

        if not self.favorites:
            ctk.CTkLabel(win, text="즐겨찾기가 비어있습니다",
                         font=ctk.CTkFont(size=13),
                         text_color=C_TEXT_DIM).pack(pady=40)
            return

        sf = ctk.CTkScrollableFrame(win, fg_color=C_BG)
        sf.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        def _rebuild_fav_list():
            for w in sf.winfo_children():
                w.destroy()
            if not self.favorites:
                ctk.CTkLabel(sf, text="즐겨찾기가 비어있습니다",
                             font=ctk.CTkFont(size=13),
                             text_color=C_TEXT_DIM).pack(pady=40)
                count_label.configure(text=f"{len(self.favorites)}개")
                return

            for item in list(self.favorites):
                row = ctk.CTkFrame(sf, fg_color=C_CARD, corner_radius=8,
                                   height=52)
                row.pack(fill="x", pady=2, padx=2)
                row.pack_propagate(False)

                # ★ v4.5: 중고나라 → 네온 그린
                source_color = C_ACCENT if item.get("source") == "번개장터" else C_JOONGNA
                ctk.CTkLabel(row, text=item.get("source", ""),
                             font=ctk.CTkFont(size=10, weight="bold"),
                             text_color=source_color).pack(side="left", padx=(10, 6), pady=8)

                # 제목 + 가격을 세로로 쌓기
                info_frame = ctk.CTkFrame(row, fg_color="transparent")
                info_frame.pack(side="left", fill="both", expand=True, pady=4)

                title = (item.get("title", ""))[:24]
                ctk.CTkLabel(info_frame, text=title,
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=C_TEXT, anchor="w").pack(anchor="w")

                price = item.get("price", "")
                if price:
                    ctk.CTkLabel(info_frame, text=price,
                                 font=ctk.CTkFont(size=11, weight="bold"),
                                 text_color=C_PRICE, anchor="w").pack(anchor="w")

                # 삭제 버튼
                ctk.CTkButton(
                    row, text="✕", width=26, height=26,
                    fg_color="transparent", hover_color="#3a2020",
                    text_color=C_RED_DIM, font=ctk.CTkFont(size=12),
                    command=lambda i=item: _remove_fav(i),
                    corner_radius=6, border_width=0
                ).pack(side="right", padx=(0, 6), pady=6)

                # 링크 버튼
                ctk.CTkButton(
                    row, text="→", width=26, height=26,
                    fg_color="transparent", hover_color=C_BTN_HOVER,
                    text_color=C_TEXT_DIM,
                    command=lambda u=item.get("url", ""): webbrowser.open(u),
                    corner_radius=6, border_width=0
                ).pack(side="right", padx=(0, 2), pady=6)

            count_label.configure(text=f"{len(self.favorites)}개")

        def _remove_fav(item):
            self.favorites = [f for f in self.favorites if f.get("id") != item.get("id")]
            save_json(FAVORITES_FILE, self.favorites)
            for cid, citem in self._card_items.items():
                if citem.get("id") == item.get("id"):
                    hb = self._card_heart_btns.get(cid)
                    if hb:
                        try:
                            hb.configure(text="♡", text_color=C_TEXT_DIM)
                        except Exception:
                            pass
            _rebuild_fav_list()

        _rebuild_fav_list()

    # ─────────────── 설정 ───────────────

    def _show_settings(self):
        win = ctk.CTkToplevel(self)
        win.title("설정")
        win.geometry("340x260")
        win.configure(fg_color=C_BG)
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text="설정",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=C_TEXT).pack(pady=12)

        frame = ctk.CTkFrame(win, fg_color=C_CARD, corner_radius=10)
        frame.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(frame, text="새로고침 간격 (초)",
                     font=ctk.CTkFont(size=12),
                     text_color=C_TEXT_DIM).pack(anchor="w", padx=12, pady=(10, 4))
        interval_var = ctk.StringVar(value=str(self.settings.get("interval", 30)))
        ctk.CTkEntry(frame, textvariable=interval_var, height=34,
                     fg_color=C_SURFACE, border_color=C_BORDER,
                     text_color=C_TEXT, border_width=1,
                     corner_radius=6).pack(fill="x", padx=12, pady=(0, 10))

        chrome_frame = ctk.CTkFrame(win, fg_color=C_CARD, corner_radius=10)
        chrome_frame.pack(fill="x", padx=16, pady=6)
        ctk.CTkLabel(chrome_frame, text="Chrome 모드",
                     font=ctk.CTkFont(size=12),
                     text_color=C_TEXT_DIM).pack(anchor="w", padx=12, pady=(10, 4))
        btn_row = ctk.CTkFrame(chrome_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(btn_row, text="Visible 전환", width=100, height=30,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      text_color=C_TEXT_DIM, font=ctk.CTkFont(size=11),
                      command=self._switch_chrome_visible,
                      corner_radius=6, border_width=0).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="Headless 전환", width=100, height=30,
                      fg_color=C_BTN, hover_color=C_BTN_HOVER,
                      text_color=C_TEXT_DIM, font=ctk.CTkFont(size=11),
                      command=self._switch_chrome_headless,
                      corner_radius=6, border_width=0).pack(side="left")

        def save():
            try:
                val = max(5, int(interval_var.get()))
                self.settings["interval"] = val
                save_json(SETTINGS_FILE, self.settings)
                win.destroy()
            except ValueError:
                pass

        ctk.CTkButton(win, text="저장", height=34,
                      fg_color=C_ACCENT, hover_color=C_ACCENT_HOVER,
                      text_color="white",
                      font=ctk.CTkFont(size=13, weight="bold"),
                      command=save, corner_radius=6, border_width=0).pack(pady=10)

    def _switch_chrome_visible(self):
        if not self._chrome_ready:
            self._set_status("먼저 Chrome을 연결하세요")
            return
        self.chrome_status.configure(text="● 전환 중…", text_color=C_YELLOW)
        def do():
            try:
                self.chrome_mgr.switch_to_visible()
                self.after(0, lambda: self.chrome_status.configure(text="● Visible", text_color=C_GREEN))
                self.after(0, lambda: self._set_status("Visible 모드"))
            except Exception as e:
                self.after(0, lambda: self._set_status(f"전환 실패: {e}"))
        threading.Thread(target=do, daemon=True).start()

    def _switch_chrome_headless(self):
        if not self._chrome_ready:
            self._set_status("먼저 Chrome을 연결하세요")
            return
        def do():
            try:
                self.chrome_mgr.switch_to_headless()
                self.after(0, lambda: self.chrome_status.configure(text="● 연결됨", text_color=C_GREEN))
                self.after(0, lambda: self._set_status("Headless 모드"))
            except Exception as e:
                self.after(0, lambda: self._set_status(f"전환 실패: {e}"))
        threading.Thread(target=do, daemon=True).start()

    # ─────────────── 스피너 ───────────────

    def _start_spinner(self):
        self._spinner_running = True
        self._animate_spinner()

    def _stop_spinner(self):
        self._spinner_running = False

    def _animate_spinner(self):
        if not self._spinner_running:
            return
        char = self._spinner_chars[self._spinner_idx % len(self._spinner_chars)]
        self._spinner_idx += 1
        current = self.status_label.cget("text")
        base = current
        for sc in self._spinner_chars:
            base = base.replace(sc, "").strip()
        self.status_label.configure(text=f"{char}  {base}")
        self.after(120, self._animate_spinner)

    def _set_status(self, text):
        self.status_label.configure(text=text)

    def _on_close(self):
        self.monitoring = False
        self._spinner_running = False
        save_json(FAVORITES_FILE, self.favorites)
        save_json(SETTINGS_FILE, self.settings)
        try:
            self.chrome_mgr.quit()
        except Exception:
            pass
        self.destroy()


# ============================================================
if __name__ == "__main__":
    app = MarketMonitorApp()
    app.mainloop()
