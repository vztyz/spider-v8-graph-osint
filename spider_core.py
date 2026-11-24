import asyncio
import re
import logging
import os
import json
import random
import datetime
from telethon import TelegramClient, functions, types
from telethon.tl.functions.channels import CreateChannelRequest, EditPhotoRequest
from telethon.tl.functions.messages import ExportChatInviteRequest
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import UploadProfilePhotoRequest
try:
    import google.generativeai as genai
except ImportError:
    pass
from telethon.errors import FloodWaitError, ChannelPrivateError, UsernameInvalidError
from telethon.tl.functions.channels import GetFullChannelRequest, GetChannelRecommendationsRequest, JoinChannelRequest
from telethon.tl.functions.contacts import ResolveUsernameRequest, SearchRequest
from database import DatabaseManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SpiderWorker:
    def __init__(self, session_name, api_id, api_hash, db_manager: DatabaseManager, proxy=None, log_callback=None, status_callback=None, test_mode=False):
        self.db = db_manager
        self.session_name = session_name
        self.log_callback = log_callback or logging.info
        self.status_callback = status_callback or (lambda stat, err: None)
        self.test_mode = test_mode
        self.is_running = True
        
        base_dir = os.path.dirname(os.path.abspath(__file__))
        session_path = os.path.join(base_dir, f"{session_name}.session")
        json_path = os.path.join(base_dir, f"{session_name}.json")
        
        device_model = "Desktop"
        system_version = "Windows 10"
        app_version = "4.14.9 x64"
        lang_code = "en"
        system_lang_code = "en"

        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    j_data = json.load(f)
                    device_model = j_data.get("device", device_model)
                    system_version = j_data.get("sdk", system_version)
                    app_version = j_data.get("app_version", app_version)
                    lang_code = j_data.get("lang_code", lang_code)
                    system_lang_code = j_data.get("system_lang_code", system_lang_code)
            except Exception:
                pass

        self.client = TelegramClient(
            session_path, 
            api_id, 
            api_hash, 
            proxy=proxy,
            device_model=device_model,
            system_version=system_version,
            app_version=app_version,
            lang_code=lang_code,
            system_lang_code=system_lang_code
        )
        
        self.proxy_name = "No Proxy"
        if proxy:
            if isinstance(proxy, dict) and proxy.get('addr'):
                self.proxy_name = f"{proxy.get('addr')}:{proxy.get('port', '?')}"
            elif isinstance(proxy, tuple) and len(proxy) >= 3:
                self.proxy_name = f"{proxy[1]}:{proxy[2]}"
        
        self.blacklist = []
        self.whitelist = []
        self.ad_triggers = []
        self.comment_triggers = []
        
        self.cfg_min_subs = 500
        self.cfg_max_depth = 15
        self.cfg_delay = 15

    def _refresh_config(self):
        settings = self.db.get_global_settings()
        self.cfg_min_subs = settings.get('min_subscribers', 500)
        self.cfg_max_depth = settings.get('max_depth', 15)
        self.cfg_delay = settings.get('delay_sec', 15)
        self.cfg_gemini_key = settings.get('gemini_api_key', '')
        
        # Дефолтный промпт для комментариев (Байт/Провокация)
        default_prompt = "Напиши интригующий, слегка дерзкий комментарий (строго от 2 до 5 слов) к этому посту. Задача: заставить людей кликнуть на мой профиль. Без хэштегов и смайликов. Пост: {text}"
        self.cfg_comment_prompt = settings.get('auto_comment_prompt', default_prompt)

        keywords = self.db.get_all_keywords()
        self.blacklist = [w for w, t in keywords if t == 'blacklist']
        self.whitelist = [w for w, t in keywords if t == 'whitelist']
        self.ad_triggers = [w for w, t in keywords if t == 'ad_trigger']
        self.comment_triggers = [w for w, t in keywords if t == 'comment_trigger']

    async def run_leadgen(self, delay_min=5, delay_max=15, daily_limit=15):
        """Режим агрессивного комментинга по базе"""
        self.log_callback(f"🔥 Запущен LeadGen. Лимит: {daily_limit} шт/день. Задержка: {delay_min}-{delay_max} мин.")
        comments_sent = 0
        
        while self.is_running:
            self._refresh_config()
            
            if comments_sent >= daily_limit:
                self.log_callback("🛑 Дневной лимит комментов достигнут! Ухожу в глубокий сон на 24 часа...")
                await asyncio.sleep(86400)
                comments_sent = 0  # Сбрасываем счетчик на следующие сутки
                continue
            
            # Сначала проверяем выживаемость старых комментов
            await self.verify_old_comments()
            
            # Берем из БД один канал, который:
            # 1. Одобрен (approved/enriching)
            # 2. Не в токсичном списке (whitelist_status != 'toxic')
            # 3. Имеет комменты (has_comments = 1)
            query = """SELECT telegram_id, username FROM channels 
                       WHERE status IN ('approved', 'enriching') 
                       AND has_comments = 1 
                       AND whitelist_status != 'toxic' 
                       ORDER BY RANDOM() LIMIT 1"""
            
            row = self.db._execute(query, fetch=True)
            if not row:
                self.log_callback("💤 Нет доступных каналов для комментинга. Сплю 30 сек...")
                await asyncio.sleep(30)
                continue
                
            channel_id, username = row[0], row[1]
            target = username if username else channel_id
            
            try:
                entity, is_frozen = await self.get_entity_robust(target)
                if not entity:
                    self.db.update_channel_status(channel_id, 'rejected', username=str(target))
                    await asyncio.sleep(30)
                    continue
                
                # --- ИМИТАЦИЯ ЖИВОГО ПОВЕДЕНИЯ ПЕРЕД КОММЕНТОМ ---
                self.log_callback(f"🚶‍♂️ Зашел в целевой канал {target}. Изучаю контент...")
                await self.simulate_human_reading(entity, target)
                
                offline_time = random.uniform(3, 10) # Уходим в оффлайн на 3-10 минут
                self.log_callback(f"📱 Свернул Telegram. Вернусь через {round(offline_time, 1)} минут, чтобы оставить коммент.")
                await asyncio.sleep(offline_time * 60)
                
                self.log_callback(f"⚡ Вернулся в {target}. Ищу свежий пост...")
                # ------------------------------------------------

                # Ищем свежий пост с текстом (до 5 последних)
                post_found = False
                async for post in self.client.iter_messages(entity, limit=5):
                    if post.text:
                        post_found = True
                        post_age = datetime.datetime.now(datetime.timezone.utc) - post.date
                        if post_age.total_seconds() < 86400:
                            success = await self.attempt_neuro_comment(entity, post, channel_id)
                            if success:
                                comments_sent += 1
                                delay_sec = random.randint(delay_min * 60, delay_max * 60)
                                self.log_callback(f"⏳ [Безопасность] Коммент оставлен. Сплю {delay_sec // 60} минут...")
                                await asyncio.sleep(delay_sec)
                            else:
                                self.log_callback("⏳ Жду 1 минуту перед следующим каналом...")
                                await asyncio.sleep(60)
                        else:
                            self.log_callback(f"⏭ Пост на {target} слишком старый. Ищу другой канал...")
                            await asyncio.sleep(60)
                        break
                
                if not post_found:
                    self.log_callback(f"⏭ В {target} нет текстовых постов. Пропускаю...")
                    await asyncio.sleep(30)
            except Exception as e:
                self.log_callback(f"⚠️ LeadGen ошибка на {target}: {str(e)}")
                # Если канал недоступен, даем страйк или откидываем
                if "No user has" in str(e) or "banned" in str(e).lower():
                    self.db.update_channel_status(channel_id, 'rejected', username=str(target))
                await asyncio.sleep(30)

    async def run_scout(self, seed_channel):
        """Режим Скаут: Запрашиваем рекомендации от 1 канала и передаем веб-скраперу"""
        self.log_callback(f"🕷️ Scout: Ищу рекомендации (похожие каналы) для {seed_channel}...")
        try:
            entity, is_frozen = await self.get_entity_robust(seed_channel)
            
            if not entity:
                return # Детальная ошибка уже выведена внутри get_entity_robust
                
            recs = await self.client(GetChannelRecommendationsRequest(channel=entity))
            
            from gogle import link_queue
            
            count = 0
            for rc in recs.chats:
                if not self.is_running: break
                if rc.username:
                    link = f"https://t.me/{rc.username}"
                    # Добавляем в базу как очередь
                    self.db.add_channel(rc.id, f"@{rc.username}", rc.title, "", 0, False, status='queue', proxy_name=self.proxy_name)
                    # Кидаем ссылку веб-парсерам для глубокого анализа (сабы, комменты)
                    link_queue.put({"url": link, "text": f"[Scout] Рекомендация от {seed_channel}"})
                    count += 1
                    
            self.log_callback(f"✅ Scout собрал {count} каналов! Отправляю их в фоновый Web Парсер...")
            
            # Фоново "дергаем" эндпоинт запуска Sniper Checker'ов (с пустыми дорками)
            import requests
            try:
                requests.post("http://127.0.0.1:8050/api/sniper/start", json={"queries": []}, timeout=2)
                self.log_callback("✅ Web Парсер запущен в фоне. Открой вкладку Google Sniper!")
            except: pass
            
            self.log_callback("🏁 Работа Scout завершена. Аккаунт отключен (IDLE) для безопасности.")
            
        except Exception as e:
            self.log_callback(f"❌ Scout ошибка на {seed_channel}: {str(e)}")

    async def get_entity_robust(self, clean_name):
        """Бронебойный поиск канала, обходящий теневой бан Telegram на поиск (not in use)"""
        clean_name = str(clean_name).lstrip('@').strip()
        if "t.me/" in clean_name:
            clean_name = clean_name.split("t.me/")[-1].split("/")[0].split("?")[0]
            
        if clean_name.lstrip('-').isdigit():
            try:
                return await self.client.get_entity(int(clean_name)), False
            except: pass
                
        # 4 разных метода поиска для обхода ограничений
        methods = [
            lambda: self.client.get_entity(clean_name),
            lambda: self.client(ResolveUsernameRequest(clean_name)),
            lambda: self.client(functions.contacts.SearchRequest(q=clean_name, limit=1)),
            lambda: self.client.get_entity(f"t.me/{clean_name}")
        ]
        
        for i, method in enumerate(methods):
            try:
                res = await method()
                if i == 1 and res and hasattr(res, 'chats') and res.chats: 
                    return res.chats[0], False
                if i == 2 and res and hasattr(res, 'chats') and res.chats: 
                    return res.chats[0], False
                if res and not hasattr(res, 'chats'): 
                    return res, False
            except Exception as e:
                err_str = str(e).lower()
                if "frozen" in err_str:
                    self.log_callback(f"🚫 АККАУНТ ЗАМОРОЖЕН TELEGRAM! Остановка поиска.")
                    return None, True
                if "flood" in err_str:
                    self.log_callback(f"⚠️ Telegram выдал FloodWait на поиск... Сплю 5 сек.")
                    await asyncio.sleep(5)
            await asyncio.sleep(1.5)

        self.log_callback(f"❌ Канал @{clean_name} недоступен. Аккаунт в теневом бане на поиск (SpamBlock) или канал удален.")
        return None, False

    async def verify_old_comments(self):
        # Модуль Check-Back: Проверка выживаемости комментариев
        comments = self.db.get_comments_to_check(self.session_name)
        for db_id, channel_id, discussion_id, comment_id in (comments or []):
            try:
                # Ищем коммент либо в чате обсуждения, либо в самом канале
                target = discussion_id if discussion_id else channel_id
                msg = await self.client.get_messages(target, ids=comment_id)
                
                if not msg or getattr(msg, 'empty', True):
                    self.log_callback(f"❌ Коммент удален админом! Страйк каналу {channel_id}.")
                    self.db.process_comment_result(db_id, channel_id, False)
                else:
                    self.log_callback(f"🛡️ Коммент выжил (>2 часов)! Канал добавлен в Whitelist.")
                    self.db.process_comment_result(db_id, channel_id, True)
                await asyncio.sleep(1.5)
            except Exception as e:
                self.log_callback(f"⚠️ Ошибка Check-Back: {str(e)}")

    async def start(self):
        try:
            await self.client.connect()
            if not await self.client.is_user_authorized():
                self.log_callback(f"❌ [{self.session_name}] Ошибка авторизации!")
                self.status_callback("error", "Unauthorized")
                return
            self.log_callback(f"✅ [{self.session_name}] Авторизован успешно.")
            if self.test_mode:
                await self.client.disconnect()
                self.status_callback("idle", "") 
                return
            self.status_callback("running", "")
        except Exception as e:
            self.log_callback(f"❌ Ошибка: {str(e)}")
            self.status_callback("error", str(e))
            if self.client.is_connected():
                await self.client.disconnect()
            return
        
        while self.is_running:
            self._refresh_config()
            
            # --- ВЫЗОВ МОДУЛЯ CHECK-BACK ПЕРЕД НОВЫМ ЦИКЛОМ ---
            await self.verify_old_comments()
            # --------------------------------------------------

            channel = self.db.get_next_channel_in_queue()
            if not channel:
                await asyncio.sleep(10)
                continue

            identifier = channel['username']
            if identifier and not str(identifier).startswith('@') and str(identifier).lstrip('-').isdigit():
                identifier = int(identifier)
            elif not identifier and channel['telegram_id'] != 0:
                identifier = int(channel['telegram_id'])

            self.log_callback(f"🔍 [{self.session_name}] Анализ: {identifier}")
            try:
                await self.process_channel(identifier, channel['telegram_id'])
                await asyncio.sleep(self.cfg_delay) 
                self.status_callback("running", "")
            except FloodWaitError as e:
                self.log_callback(f"⚠️ FloodWait: {e.seconds} сек.")
                self.status_callback("floodwait", f"Wait {e.seconds}s")
                self.db.update_channel_status(channel['telegram_id'], 'queue')
                await asyncio.sleep(e.seconds)
            except Exception as e:
                error_msg = str(e)
                self.log_callback(f"❌ Критическая ошибка на {identifier}: {error_msg}")
                if any(x in error_msg.lower() for x in ["timeout", "connection", "network", "rpcerror_500"]):
                    self.db.update_channel_status(channel['telegram_id'], 'queue')
                else:
                    self.db.update_channel_status(channel['telegram_id'], 'rejected')
                    self.db._execute("UPDATE channels SET description = ? WHERE telegram_id = ?", (f"ERR: {error_msg}", channel['telegram_id']))


    async def process_channel(self, identifier, db_internal_id):
        original_identifier = identifier
        
        if isinstance(identifier, str):
            clean_name = identifier.lstrip('@').strip()
            identifier = clean_name
        else:
            clean_name = str(identifier)
        
        entity, is_frozen_account = await self.get_entity_robust(clean_name)

        if is_frozen_account:
            self.log_callback(f"🚫 АККАУНТ ЗАМОРОЖЕН! Канал {clean_name} не может быть найден.")
            self.db.update_channel_status(db_internal_id, 'rejected', username=str(clean_name))
            if db_internal_id != 0:
                self.db._execute("UPDATE channels SET description = 'ERR: Frozen Account' WHERE telegram_id = ?", (db_internal_id,))
            return

        if not entity:
            self.db.update_channel_status(db_internal_id, 'rejected', username=str(clean_name))
            if db_internal_id != 0:
                self.db._execute("UPDATE channels SET description = 'ERR: Not found' WHERE telegram_id = ?", (db_internal_id,))
            return

        try:
            full_channel = await self.client(GetFullChannelRequest(channel=entity))
            chat = full_channel.chats[0]
            full_info = full_channel.full_chat
            
            has_comments = True if full_info.linked_chat_id else False
            subs_count = full_info.participants_count or 0
            
            if not has_comments:
                self.log_callback(f"[-] {identifier} отклонен: Комментарии закрыты.")
                self.db.add_channel(chat.id, f"@{chat.username}" if chat.username else str(chat.id), chat.title, "SKIP: Comments closed", subs_count, False, status='rejected', proxy_name=self.proxy_name)
                return

            if subs_count < self.cfg_min_subs:
                 self.log_callback(f"[-] {identifier} отброшен: {subs_count} саб.")
                 self.db.add_channel(chat.id, f"@{chat.username}" if chat.username else str(chat.id), chat.title, f"SKIP: Only {subs_count} subs", subs_count, True, status='rejected', proxy_name=self.proxy_name)
                 return

            username_formatted = f"@{chat.username}" if chat.username else str(chat.id)
            
            self.db.add_channel(chat.id, username_formatted, chat.title, full_info.about or "", subs_count, True, status='processing', proxy_name=self.proxy_name)
            
            db_internal_id = chat.id
                
        except Exception as e:
            error_msg = str(e)
            if any(x in error_msg.lower() for x in ["private", "banned", "channel_private", "chat_admin_required"]):
                self.db.update_channel_status(db_internal_id, 'rejected', username=str(identifier))
                if db_internal_id != 0:
                    self.db._execute("UPDATE channels SET description = ? WHERE telegram_id = ?", (f"ERR: {error_msg}", db_internal_id))
            else:
                self.db.update_channel_status(db_internal_id, 'queue', username=str(identifier))
            return

        try:
            await asyncio.sleep(2)
            recs = await self.client(GetChannelRecommendationsRequest(channel=entity))
            for rc in recs.chats:
                runame = f"@{rc.username}" if rc.username else str(rc.id)
                self.db.add_channel(rc.id, runame, rc.title, "", 0, False, status='queue', proxy_name=self.proxy_name)
                self.db.add_graph_link(chat.id, rc.id, 'similar')
        except: pass

        raw_posts = []
        post_count = 0
        async for post in self.client.iter_messages(entity, limit=self.cfg_max_depth):
            if not post.text: continue
            raw_posts.append(post.text[:200])
            post_count += 1
            
            # Комментинг изолирован. В режиме разведки бот только собирает граф.
            
            mentions = re.findall(r'@([a-zA-Z0-9_]+)|t\.me/([a-zA-Z0-9_]+)', post.text)
            for m in mentions:
                m_name = m[0] or m[1]
                if m_name and m_name.lower() != str(chat.username).lower():
                    m_f = f"@{m_name}"
                    self.db.add_channel(0, m_f, "Unknown", "", 0, False, status='queue', proxy_name=self.proxy_name)
                    self.db.add_graph_link(chat.id, m_f, 'mention')

            if post.replies and post.replies.replies > 0:
                try:
                    async for com in self.client.iter_messages(entity, reply_to=post.id, limit=20):
                        if not com.text: continue
                        if self.comment_triggers and any(cw in com.text.lower() for cw in self.comment_triggers):
                            link = f"https://t.me/{chat.username}/{post.id}?comment={com.id}" if chat.username else f"https://t.me/c/{str(chat.id).replace('-100','')}/{post.id}"
                            self.db.add_comment_for_review(chat.id, "Lead", com.text, link)
                            self.log_callback(f"🎯 Лид в {username_formatted}!")
                except: pass

        self.db.update_channel_content(chat.id, "\n---\n".join(raw_posts))
        self.db.update_channel_status(chat.id, 'approved')
        
    async def setup_profile_funnel(self, bio_template, offer_text, target_channel=None, main_channel=None, channel_title="My Blog", first_name="User", last_name="", is_private_request=False):
        try:
            self.log_callback(f"🛠 [{self.session_name}] Начинаю авто-настройку воронки...")
            
            invite_link = target_channel
            
            avatars_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "avatars")
            acc_avatar = os.path.join(avatars_dir, f"{self.session_name}_acc.jpg")
            chan_avatar = os.path.join(avatars_dir, f"{self.session_name}_chan.jpg")

            if not target_channel:
                self.log_callback(f"🏗 Создаю канал-прокладку '{channel_title}'...")
                await asyncio.sleep(random.uniform(2.0, 4.0)) # Пауза как будто юзер нажимает "Создать канал"
                
                created_channel = await self.client(CreateChannelRequest(
                    title=channel_title,
                    about=bio_template[:255] if bio_template else "Welcome!",
                    megagroup=False
                ))
                channel_id = created_channel.chats[0].id
                channel_entity = await self.client.get_entity(channel_id)
                
                # Установка аватарки канала
                if os.path.exists(chan_avatar):
                    self.log_callback(f"🖼 Гружу аватарку для канала...")
                    await asyncio.sleep(random.uniform(1.5, 3.0)) # Пауза на выбор файла
                    file = await self.client.upload_file(chan_avatar)
                    await self.client(EditPhotoRequest(channel=channel_entity, photo=file))
                    
                # Вставка ссылки на Main канал
                if main_channel:
                    if "{link}" in offer_text:
                        offer_text = offer_text.replace("{link}", main_channel)
                    else:
                        offer_text += f"\n\n👉 {main_channel}"
                        
                post_img = os.path.join(avatars_dir, f"{self.session_name}_post.jpg")
                if os.path.exists(post_img):
                    self.log_callback(f"📝 Пишу пост-оффер с картинкой...")
                    await asyncio.sleep(random.uniform(2.0, 5.0)) # Пауза на "написание" текста
                    await self.client.send_message(channel_entity, offer_text, file=post_img)
                else:
                    self.log_callback(f"📝 Пишу пост-оффер...")
                    await asyncio.sleep(random.uniform(2.0, 4.0))
                    await self.client.send_message(channel_entity, offer_text)
                    
                self.log_callback(f"🔗 Настраиваю ссылки...")
                await asyncio.sleep(random.uniform(1.0, 2.0))
                invite = await self.client(ExportChatInviteRequest(
                    peer=channel_entity,
                    request_needed=is_private_request
                ))
                invite_link = invite.link
                self.db._execute("UPDATE profiles SET created_channel = ? WHERE name = ?", (invite_link, self.session_name))
                self.log_callback(f"✅ Прокладка создана! Ссылка: {invite_link}")
            else:
                self.log_callback(f"🔗 Использую основной канал: {target_channel}")
                if not invite_link.startswith('http'):
                    invite_link = f"https://t.me/{invite_link.replace('@', '')}"
                self.db._execute("UPDATE profiles SET target_channel = ? WHERE name = ?", (invite_link, self.session_name))
                await asyncio.sleep(random.uniform(1.0, 2.0))

            # 4. Обновляем Имя и BIO аккаунта
            self.log_callback(f"⚙️ Перехожу в настройки профиля...")
            await asyncio.sleep(random.uniform(2.0, 4.0)) # Имитация перехода в настройки
            
            self.log_callback(f"📝 Меняю имя на: {first_name} {last_name}")
            final_bio = f"{bio_template} 👉 {invite_link}"
            if len(final_bio) > 70:
                final_bio = final_bio[:67] + "..."
            
            await self.client(UpdateProfileRequest(first_name=first_name, last_name=last_name, about=final_bio))
            await asyncio.sleep(random.uniform(3.0, 5.0)) # Обязательная пауза после смены БИО (очень частый триггер бана)
            
            # 5. Установка Аватарки Аккаунта
            if os.path.exists(acc_avatar):
                self.log_callback(f"🖼 Загружаю аватарку профиля...")
                await asyncio.sleep(random.uniform(1.5, 3.5))
                file = await self.client.upload_file(acc_avatar)
                await self.client(UploadProfilePhotoRequest(file=file))
            elif os.path.exists(avatars_dir):
                images = [f for f in os.listdir(avatars_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg')) and not f.endswith('_acc.jpg') and not f.endswith('_chan.jpg')]
                if images:
                    random_image = random.choice(images)
                    photo_path = os.path.join(avatars_dir, random_image)
                    self.log_callback(f"🖼 Загружаю аватарку профиля...")
                    await asyncio.sleep(random.uniform(1.5, 3.5))
                    file = await self.client.upload_file(photo_path)
                    await self.client(UploadProfilePhotoRequest(file=file))
            
            self.log_callback(f"✅ [{self.session_name}] Воронка успешно создана!")
            
        except Exception as e:
            self.log_callback(f"❌ Ошибка создания воронки: {str(e)}")

    async def simulate_human_reading(self, entity, channel_name):
        """Эмуляция реального просмотра канала человеком"""
        try:
            # 1. Запрашиваем инфу о канале (человек тапнул на шапку)
            await self.client(GetFullChannelRequest(channel=entity))
            bio_read_time = random.uniform(5, 15)
            self.log_callback(f"👀 [{channel_name}] Читаю описание канала ({round(bio_read_time)} сек)...")
            await asyncio.sleep(bio_read_time)
            
            # 2. Листаем посты
            msg_count = random.randint(2, 5)
            self.log_callback(f"📜 [{channel_name}] Листаю ленту (читаю {msg_count} постов)...")
            
            async for msg in self.client.iter_messages(entity, limit=msg_count):
                if not self.is_running: break
                if msg.text:
                    # Высчитываем время чтения в зависимости от длины текста (примерно 300 символов в минуту)
                    read_time = len(msg.text) * 0.05 
                    read_time = min(max(read_time, 3), 45) # Не меньше 3 сек, не больше 45 сек на пост
                    self.log_callback(f"   👁 Читаю пост... ({round(read_time, 1)} сек)")
                    await asyncio.sleep(read_time)
                else:
                    # Если это просто картинка/видео
                    await asyncio.sleep(random.uniform(2, 6))
        except Exception as e:
            self.log_callback(f"⚠️ Ошибка при чтении канала {channel_name}: {str(e)}")

    async def warmup_account(self, count=3, min_delay=5, max_delay=15):
        """Модуль Si-защиты: Разогрев сессии перед действием"""
        self.log_callback(f"🛡️ [Anti-Ban] Разогрев сессии (Jitter). Каналов для имитации: {count}.")
        try:
            dummy_channels = ['durov', 'telegram', 'toncoin', 'ru_telegram', 'telegramtips', 'tnews_ru', 'tginfo', 'tonblockchain']
            random.shuffle(dummy_channels)
            selected = dummy_channels[:count]
            
            for i, channel in enumerate(selected):
                if not self.is_running: break
                try:
                    self.log_callback(f"🔄 Прогрев ({i+1}/{count}): Ищу канал @{channel}...")
                    # Человеческая пауза перед поиском
                    await asyncio.sleep(random.uniform(2, 5)) 
                    ent = await self.client.get_entity(channel)
                    
                    # Симулируем вдумчивое чтение канала
                    await self.simulate_human_reading(ent, f"@{channel}")
                    
                    delay_minutes = random.uniform(min_delay, max_delay)
                    self.log_callback(f"☕ Закрыл Telegram. Отдыхаю {round(delay_minutes, 1)} минут...")
                    await asyncio.sleep(delay_minutes * 60)
                except FloodWaitError as e:
                    self.log_callback(f"⚠️ [ANTI-BAN] Telegram просит подождать {e.seconds} сек. Засыпаю...")
                    await asyncio.sleep(e.seconds + 10)
                except Exception as e:
                    self.log_callback(f"⚠️ Пропуск @{channel}: {str(e)[:50]}")
                    await asyncio.sleep(10) # Защитная пауза при любой ошибке
                    
            self.log_callback(f"✅ Разогрев сессии завершен. Перехожу к боевым задачам.")
        except Exception as e:
            self.log_callback(f"⚠️ Ошибка при прогреве: {str(e)}")

    async def attempt_neuro_comment(self, entity, post, channel_id):
        try:
            if 'genai' not in globals():
                self.log_callback("❌ Модуль ИИ не загружен! Установи: pip install google-generativeai")
                return False
                
            if not self.cfg_gemini_key:
                self.log_callback("❌ Ошибка: Не указан API ключ Gemini! Добавь его в Graph AI View.")
                return False
                
            genai.configure(api_key=self.cfg_gemini_key)
            model = genai.GenerativeModel("gemini-3.1-flash-lite-preview")
            
            # 1. Генерация ответа ИИ
            prompt = self.cfg_comment_prompt.replace("{text}", post.text[:500])
            response = model.generate_content(prompt)
            comment_text = response.text.strip().replace('"', '')
            
            if not comment_text: return
            self.log_callback(f"🧠 ИИ сгенерировал коммент: {comment_text}")

            # 2. Si-защита: Имитация чтения и набора текста
            # Задержка 0.2 сек на каждый символ (как будто человек печатает)
            typing_delay = len(comment_text) * 0.2
            if typing_delay < 2.0: typing_delay = 2.0
            
            self.log_callback(f"⏳ Si-защита: Имитация печати ({round(typing_delay, 1)} сек)...")
            try:
                # Отправляем статус "Печатает..." для реалистичности
                await self.client(functions.messages.SetTypingRequest(peer=entity, action=types.SendMessageTypingAction()))
            except: pass
            
            await asyncio.sleep(typing_delay)

            # 3. Отправка комментария
            # comment_to=post автоматически находит группу обсуждения и отправляет туда реплай!
            sent_msg = await self.client.send_message(entity, comment_text, comment_to=post)
            
            # 4. Запись в базу
            discussion_id = getattr(sent_msg, 'chat_id', 0)
            self.db.log_comment(self.session_name, channel_id, post.id, sent_msg.id, discussion_id)
            self.log_callback(f"✅ Комментарий успешно оставлен!")
            return True
            
        except Exception as e:
            error_msg = str(e)
            if "SLOWMODE_WAIT" in error_msg:
                self.log_callback(f"⚠️ Комментинг: Включен Slowmode.")
            elif "CHAT_WRITE_FORBIDDEN" in error_msg:
                self.log_callback(f"🚫 Комментинг: Запрещено писать (нужна подписка или бан).")
            elif "DISCUSSION_POST_NOT_FOUND" in error_msg:
                self.log_callback(f"⚠️ Комментинг: Группа для комментов не найдена/отключена.")
            else:
                self.log_callback(f"⚠️ Ошибка комментирования: {error_msg}")
        
        return False