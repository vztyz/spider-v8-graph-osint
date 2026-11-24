import os
import time
import random
import urllib.parse
import queue
import requests
import re
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

try:
    import undetected_chromedriver as uc
    HAS_UC = True
except ImportError:
    HAS_UC = False

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

link_queue = queue.Queue()

def parse_subscribers(text):
    if not text: return 0
    text = text.lower().replace('subscribers', '').replace('подписчиков', '').replace('members', '').replace('участников', '').strip()
    first_part = text.split()[0] if text.split() else ""
    if 'k' in first_part:
        return int(float(first_part.replace('k', '')) * 1000)
    if 'm' in first_part:
        return int(float(first_part.replace('m', '')) * 1000000)
    digits = ''.join(filter(str.isdigit, first_part))
    return int(digits) if digits else 0

class CheckerWorker:
    def __init__(self):
        self.is_running = True
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        self.on_found = None  # Стандартный коллбэк вместо pyqtSignal

    def run(self):
        while self.is_running:
            try:
                item = link_queue.get(timeout=2)
                if item == "STOP": break

                link = item['url']
                text_desc = item['text']
                channel_name = link.strip('/').split('/')[-1]
                
                # Игнорируем системные прокси
                session = requests.Session()
                session.trust_env = False 
                
                s_url = f"https://t.me/s/{channel_name}"
                r_s = session.get(s_url, headers=self.headers, timeout=7, proxies={"http": None, "https": None})
                
                if r_s.status_code == 429:
                    time.sleep(5)
                    link_queue.put(item) # Возвращаем в очередь при лимите ТГ
                    continue

                soup_s = BeautifulSoup(r_s.text, 'html.parser')

                if "tgme_page_title" not in r_s.text:
                    continue

                is_open = 1 if soup_s.find(class_="tgme_widget_message_reply") or "Leave a comment" in r_s.text else 0
                posts = soup_s.find_all('div', class_='tgme_widget_message_text', limit=10)
                last_posts = "\n---\n".join([p.get_text(separator=' ', strip=True) for p in posts])

                subs_count = 0
                chat_type = "Канал/Чат"
                
                extra_div = soup_s.find('div', class_='tgme_page_extra')
                if extra_div:
                    extra_text = extra_div.text.lower()
                    subs_count = parse_subscribers(extra_text)
                    if "members" in extra_text or "участников" in extra_text:
                        chat_type = "Группа/Чат"
                        is_open = 1

                result_data = {
                    "link": link, "username": f"@{channel_name}", "type": chat_type,
                    "is_open": is_open, "subs": subs_count,
                    "desc": text_desc.replace('\n', ' | ')[:200], "last_posts": last_posts
                }
                
                if self.on_found:
                    self.on_found(result_data)
                    
                time.sleep(random.uniform(0.3, 1.0)) 

            except queue.Empty: continue
            except Exception: pass

    def stop(self): self.is_running = False


class ScraperWorker:
    def __init__(self, queries, pages_count):
        self.queries = queries
        self.pages_count = pages_count
        self.is_running = True
        self.unique_links = set()
        self.on_status = None # Стандартный коллбэк для логов

    def _emit_status(self, msg):
        if self.on_status: self.on_status(msg)

    def run(self):
        # Жесткая очистка прокси и фикс SSL для WebDriver Manager
        for k in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'all_proxy', 'ALL_PROXY']:
            os.environ.pop(k, None)
        os.environ['WDM_SSL_VERIFY'] = '0'
        os.environ['WDM_LOG_LEVEL'] = '0'

        options = None
        if HAS_UC:
            self._emit_status("Запуск Anti-Detect браузера...")
            try:
                options = uc.ChromeOptions()
                options.add_argument("--disable-blink-features=AutomationControlled")
                options.add_argument("--no-proxy-server")
                options.add_argument("--start-maximized")
                driver = uc.Chrome(options=options, headless=False)
            except Exception as e:
                self._emit_status(f"⚠️ UC не запущен, откат к обычному Chrome: {str(e)}")
                options = None
        
        if options is None:
            options = Options()
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option('useAutomationExtension', False)
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--no-proxy-server")
            options.add_argument("--start-maximized")
            
            try: 
                driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
            except: 
                driver = webdriver.Chrome(options=options)
                
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            })
            
        try:
            for q_idx, dork in enumerate(self.queries):
                if not self.is_running: break
                for page in range(self.pages_count):
                    if not self.is_running: break
                    
                    start_index = page * 10
                    self._emit_status(f"🔎 Гуглим: {dork[:30]}... ({q_idx+1}/{len(self.queries)} | Стр {page+1})")
                    query_url = f"https://www.google.com/search?q={urllib.parse.quote(dork)}&start={start_index}"
                    driver.get(query_url)
                    
                    captcha_alerted = False
                    while "sorry/index" in driver.current_url:
                        self._emit_status("⚠️ КАПЧА! Разверни окно Chrome и нажми 'Я не робот'...")
                        if not captcha_alerted:
                            captcha_alerted = True
                        for _ in range(30):
                            if not self.is_running: break
                            time.sleep(0.1)
                        if not self.is_running: break

                    # Дробим долгий sleep на мелкие, чтобы мгновенно реагировать на Stop
                    for _ in range(int(random.uniform(15, 25))):
                        if not self.is_running: break
                        time.sleep(0.1)

                    js_code = """
                    var data =[];
                    var items = document.querySelectorAll('a');
                    for (var i = 0; i < items.length; i++) {
                        if (items[i].href.includes('t.me/')) {
                            var parent = items[i].closest('.g, .MjjYud');
                            data.push({"url": items[i].href, "text": parent ? parent.innerText : items[i].innerText});
                        }
                    }
                    return data;
                    """
                    found_items = driver.execute_script(js_code)

                    for item in found_items:
                        match = re.search(r't\.me/(?:s/)?([a-zA-Z0-9_]+)', item['url'])
                        if match:
                            channel_name = match.group(1)
                            if channel_name.lower() in ['share', 'c', 'joinchat', 'iv', 'setlanguage']: continue
                            link = f"https://t.me/{channel_name}"
                            if link not in self.unique_links:
                                self.unique_links.add(link)
                                link_queue.put({"url": link, "text": item['text']})

        except Exception as e: self._emit_status(f"❌ Ошибка Google: {str(e)}")
        finally:
            try: driver.quit()
            except: pass
            link_queue.put("STOP") 

    def stop(self): self.is_running = False