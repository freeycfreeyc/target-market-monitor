import customtkinter as ctk
from PIL import Image
import requests
import io
import webbrowser
import threading
import time
import feedparser
import urllib.parse

# UI 기본 설정
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("dark-blue")

# 미니멀 테마를 위한 핵심 배경색 통일 (이 색상으로 스크롤바를 위장시킵니다)
APP_BG = "#1e1e1e"

class MarketMonitorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("중고장터 실시간 모니터링 최종 완결판")
        self.geometry("750x850")
        self.configure(fg_color=APP_BG) # 전체 배경색 적용

        self.is_monitoring = False
        self.seen_items = set()
        self.favorites = {}  
        self.active_keywords = []
        self.main_blocks = [] 

        self.setup_ui()

    def setup_ui(self):
        self.top_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.top_frame.pack(pady=(10, 5), padx=10, fill="x")

        self.search_entry = ctk.CTkEntry(self.top_frame, placeholder_text="검색어 입력 후 Enter", width=350, fg_color="#2b2b2b", border_color="#444444")
        self.search_entry.pack(side="left", padx=10, pady=15)
        self.search_entry.bind("<Return>", self.add_tag)

        self.toggle_btn = ctk.CTkButton(self.top_frame, text="시작", width=80, fg_color="#333333", hover_color="#444444", text_color="#dddddd", command=self.toggle_monitoring)
        self.toggle_btn.pack(side="left", padx=5)

        self.fav_btn = ctk.CTkButton(self.top_frame, text="♥ 관심 목록", width=100, fg_color="#333333", hover_color="#444444", text_color="#dddddd", command=self.show_favorites_window)
        self.fav_btn.pack(side="right", padx=15)

        self.tags_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.tags_frame.pack(pady=0, padx=10, fill="x")

        self.status_label = ctk.CTkLabel(self, text="▶ 대기 중 (검색어를 입력하고 시작을 누르세요)", font=("Arial", 13), text_color="#666666")
        self.status_label.pack(pady=(5, 10))

        # 메인 스크롤 프레임 설정 (배경색과 스크롤바 레일 색상 일치)
        self.scrollable_frame = ctk.CTkScrollableFrame(self, width=700, height=650, fg_color=APP_BG, scrollbar_fg_color=APP_BG)
        self.scrollable_frame.pack(pady=0, padx=10, fill="both", expand=True)

        # [수정] transparent 대신 배경색(APP_BG)을 사용하여 투명한 것처럼 위장
        self.scrollable_frame.configure(scrollbar_button_color=APP_BG, scrollbar_button_hover_color=APP_BG)

        def show_scrollbar(e):
            self.scrollable_frame.configure(scrollbar_button_color="#444444", scrollbar_button_hover_color="#555555")

        def hide_scrollbar(e):
            try:
                # 현재 마우스 좌표와 프레임의 영역을 비교
                x, y = self.winfo_pointerxy()
                wx = self.scrollable_frame.winfo_rootx()
                wy = self.scrollable_frame.winfo_rooty()
                ww = self.scrollable_frame.winfo_width()
                wh = self.scrollable_frame.winfo_height()
                
                # 마우스가 프레임(매물 리스트) 안에 있다면 스크롤바를 숨기지 않음
                if wx <= x <= wx + ww and wy <= y <= wy + wh:
                    return 
                
                # 마우스가 완전히 밖으로 나갔을 때 배경색으로 위장
                self.scrollable_frame.configure(scrollbar_button_color=APP_BG, scrollbar_button_hover_color=APP_BG)
            except Exception:
                pass

        # 마우스 진입/이탈 이벤트 바인딩
        self.scrollable_frame.bind("<Enter>", show_scrollbar)
        self.scrollable_frame.bind("<Leave>", hide_scrollbar)
        self.scrollable_frame._parent_canvas.bind("<Enter>", show_scrollbar)
        self.scrollable_frame._parent_canvas.bind("<Leave>", hide_scrollbar)

    def add_tag(self, event=None):
        keyword = self.search_entry.get().strip()
        if not keyword or keyword in self.active_keywords:
            self.search_entry.delete(0, 'end')
            return

        self.active_keywords.append(keyword)
        self.search_entry.delete(0, 'end')
        self.render_tags()

    def remove_tag(self, keyword):
        if keyword in self.active_keywords:
            self.active_keywords.remove(keyword)
        self.render_tags()

    def render_tags(self):
        for widget in self.tags_frame.winfo_children():
            widget.destroy()

        for idx, keyword in enumerate(self.active_keywords):
            row = idx // 6
            col = idx % 6

            tag_bg = ctk.CTkFrame(self.tags_frame, fg_color="#333333", corner_radius=15)
            tag_bg.grid(row=row, column=col, padx=5, pady=5, sticky="w")

            lbl = ctk.CTkLabel(tag_bg, text=keyword, text_color="#dddddd", font=("Arial", 12))
            lbl.pack(side="left", padx=(10, 5), pady=2)

            btn_x = ctk.CTkButton(tag_bg, text="X", width=20, height=20, fg_color="transparent", 
                                  hover_color="#555555", text_color="#aaaaaa", font=("Arial", 12),
                                  command=lambda k=keyword: self.remove_tag(k))
            btn_x.pack(side="left", padx=(0, 5), pady=2)

    def toggle_monitoring(self):
        if not self.is_monitoring:
            if not self.active_keywords:
                return
            
            self.is_monitoring = True
            self.toggle_btn.configure(text="중지", fg_color="#555555", hover_color="#666666")
            self.status_label.configure(text_color="#cccccc") 
            
            monitor_thread = threading.Thread(target=self.monitoring_loop, daemon=True)
            monitor_thread.start()
        else:
            self.is_monitoring = False
            self.toggle_btn.configure(text="시작", fg_color="#333333", hover_color="#444444")
            self.status_label.configure(text="▶ 중지됨", text_color="#666666")

    def update_status_text(self, text):
        self.after(0, lambda: self.status_label.configure(text=text))

    def monitoring_loop(self):
        spinner = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        spinner_idx = 0

        while self.is_monitoring:
            current_keywords = list(self.active_keywords)
            
            for kw in current_keywords:
                if not self.is_monitoring: break
                
                self.update_status_text(f"🔍 '{kw}' 매물 확인 중... {spinner[spinner_idx]}")
                spinner_idx = (spinner_idx + 1) % len(spinner)
                
                items = self.fetch_bunjang(kw) + self.fetch_joonggonara(kw)
                
                for item in items:
                    if item['id'] not in self.seen_items:
                        self.seen_items.add(item['id'])
                        self.after(0, self.add_item_block, item, self.scrollable_frame, True)
                
                time.sleep(2)
            
            for remaining in range(15, 0, -1):
                if not self.is_monitoring: break
                
                self.update_status_text(f"⏳ {remaining}초 후 업데이트... {spinner[spinner_idx]}")
                spinner_idx = (spinner_idx + 1) % len(spinner)
                time.sleep(1)

    def add_item_block(self, item, parent_frame, is_new=True):
        base_color = "#252525"
        hover_color = "#181818" 
        
        item_frame = ctk.CTkFrame(parent_frame, fg_color=base_color, border_width=1, border_color="#333333", corner_radius=8)
        
        if parent_frame == self.scrollable_frame:
            if is_new and self.main_blocks:
                item_frame.pack(pady=5, padx=5, fill="x", before=self.main_blocks[0])
                self.main_blocks.insert(0, item_frame)
            else:
                item_frame.pack(pady=5, padx=5, fill="x")
                self.main_blocks.append(item_frame)
        else:
            item_frame.pack(pady=5, padx=5, fill="x")

        try:
            res = requests.get(item['image_url'], timeout=3)
            img = Image.open(io.BytesIO(res.content)).resize((100, 100), Image.LANCZOS)
            photo = ctk.CTkImage(img, size=(100, 100))
        except:
            photo = ctk.CTkImage(Image.new("RGB", (100, 100), (40, 40, 40)), size=(100, 100))

        img_label = ctk.CTkLabel(item_frame, image=photo, text="")
        img_label.pack(side="left", padx=10, pady=10)
        img_label.bind("<Button-1>", lambda e: webbrowser.open(item['url']))

        info_frame = ctk.CTkFrame(item_frame, fg_color="transparent")
        info_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        
        platform_lbl = ctk.CTkLabel(info_frame, text=f"[{item['platform']}]", font=("Arial", 11), text_color="#999999")
        platform_lbl.pack(anchor="w")
        
        title_lbl = ctk.CTkLabel(info_frame, text=item['title'], font=("Arial", 14, "bold"), text_color="#eeeeee", wraplength=350, justify="left")
        title_lbl.pack(anchor="w", pady=(2, 5))
        
        price_lbl = ctk.CTkLabel(info_frame, text=item['price'], font=("Arial", 13), text_color="#dddddd")
        price_lbl.pack(anchor="w")

        is_fav = item['id'] in self.favorites
        btn_bg = "#dddddd" if is_fav else "#333333"
        btn_txt = "#222222" if is_fav else "#aaaaaa"
        
        heart_btn = ctk.CTkButton(item_frame, text="♥", width=40, fg_color=btn_bg, text_color=btn_txt, hover_color="#555555")
        heart_btn.configure(command=lambda btn=heart_btn, itm=item: self.toggle_favorite(itm, btn))
        heart_btn.pack(side="right", padx=15)

        def on_enter(e):
            item_frame.configure(fg_color=hover_color, border_color="#555555")

        def on_leave(e):
            try:
                x, y = self.winfo_pointerxy()
                wx = item_frame.winfo_rootx()
                wy = item_frame.winfo_rooty()
                ww = item_frame.winfo_width()
                wh = item_frame.winfo_height()
                
                if wx <= x <= wx + ww and wy <= y <= wy + wh:
                    return 
                
                item_frame.configure(fg_color=base_color, border_color="#333333")
            except Exception:
                pass

        hover_widgets = [item_frame, img_label, info_frame, platform_lbl, title_lbl, price_lbl]
        for w in hover_widgets:
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

    def toggle_favorite(self, item, button):
        if item['id'] in self.favorites:
            del self.favorites[item['id']]
            button.configure(fg_color="#333333", text_color="#aaaaaa", hover_color="#555555")
        else:
            self.favorites[item['id']] = item
            button.configure(fg_color="#dddddd", text_color="#222222", hover_color="#ffffff")

    def show_favorites_window(self):
        fav_win = ctk.CTkToplevel(self)
        fav_win.title("관심 목록")
        fav_win.geometry("600x500")
        fav_win.configure(fg_color=APP_BG)
        fav_win.attributes("-topmost", True)

        scroll_fav = ctk.CTkScrollableFrame(fav_win, width=550, height=450, fg_color=APP_BG, scrollbar_fg_color=APP_BG)
        scroll_fav.pack(pady=10, padx=10, fill="both", expand=True)
        
        scroll_fav.configure(scrollbar_button_color=APP_BG, scrollbar_button_hover_color=APP_BG)

        def show_fav_scrollbar(e):
            scroll_fav.configure(scrollbar_button_color="#444444", scrollbar_button_hover_color="#555555")
            
        def hide_fav_scrollbar(e):
            try:
                x, y = fav_win.winfo_pointerxy()
                wx = scroll_fav.winfo_rootx()
                wy = scroll_fav.winfo_rooty()
                ww = scroll_fav.winfo_width()
                wh = scroll_fav.winfo_height()
                if wx <= x <= wx + ww and wy <= y <= wy + wh: return
                scroll_fav.configure(scrollbar_button_color=APP_BG, scrollbar_button_hover_color=APP_BG)
            except: pass

        scroll_fav.bind("<Enter>", show_fav_scrollbar)
        scroll_fav.bind("<Leave>", hide_fav_scrollbar)
        scroll_fav._parent_canvas.bind("<Enter>", show_fav_scrollbar)
        scroll_fav._parent_canvas.bind("<Leave>", hide_fav_scrollbar)

        if not self.favorites:
            ctk.CTkLabel(scroll_fav, text="찜한 매물이 없습니다.", text_color="#999999").pack(pady=20)
        else:
            for item_id in self.favorites:
                self.add_item_block(self.favorites[item_id], scroll_fav, is_new=False)

    def fetch_bunjang(self, keyword):
        try:
            url = f"https://api.bunjang.co.kr/api/1/find_v2.json?q={urllib.parse.quote(keyword)}&order=date"
            data = requests.get(url, timeout=5).json()
            results = []
            
            for i in data.get('list', []):
                if i.get('ad') or i.get('is_ad'):
                    continue
                    
                results.append({
                    'id': f"bj_{i.get('pid')}", 'platform': "번개장터", 'title': i.get('name'),
                    'price': f"{int(i.get('price', 0)):,}원", 'image_url': i.get('product_image'),
                    'url': f"https://bunjang.co.kr/products/{i.get('pid')}"
                })
                if len(results) >= 3:
                    break
            return results
        except: return []

    def fetch_joonggonara(self, keyword):
        try:
            feed = feedparser.parse(f"https://cafe.rss.naver.com/joonggonara?q={urllib.parse.quote(keyword)}")
            return [{
                'id': f"jg_{e.link}", 'platform': "중고나라", 'title': e.title,
                'price': "본문 확인", 'image_url': "https://via.placeholder.com/100", 'url': e.link
            } for e in feed.entries[:3]]
        except: return []

if __name__ == "__main__":
    app = MarketMonitorApp()
    app.mainloop()