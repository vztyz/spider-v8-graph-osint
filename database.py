import sqlite3
import datetime
import threading
import hashlib
import os

class DatabaseManager:
    def __init__(self, db_name="spider_data.db"):
        self.db_name = db_name
        self._lock = threading.Lock()
        self._init_db()

    def _execute(self, query, params=(), fetch=False, fetchall=False):
        with self._lock:
            with sqlite3.connect(self.db_name, timeout=20.0) as conn:
                cursor = conn.cursor()
                cursor.execute(query, params)
                if fetch: 
                    return cursor.fetchone()
                if fetchall: 
                    return cursor.fetchall()
                conn.commit()

    def _init_db(self):
        queries =[
            """CREATE TABLE IF NOT EXISTS channels (
                telegram_id INTEGER PRIMARY KEY, 
                username TEXT, 
                title TEXT,
                subscribers INTEGER, 
                has_comments BOOLEAN, 
                status TEXT DEFAULT 'queue',
                last_scraped TIMESTAMP
            )""",
            """CREATE TABLE IF NOT EXISTS graph_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                source_id INTEGER,
                target_id INTEGER, 
                link_type TEXT, 
                UNIQUE(source_id, target_id, link_type)
            )""",
            """CREATE TABLE IF NOT EXISTS comments_review (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                channel_id INTEGER,
                role TEXT, 
                text TEXT, 
                link TEXT UNIQUE, 
                status TEXT DEFAULT 'pending'
            )""",
            """CREATE TABLE IF NOT EXISTS keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                word TEXT UNIQUE, 
                type TEXT, 
                weight TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                name TEXT UNIQUE,
                api_id TEXT, 
                api_hash TEXT, 
                proxy_type TEXT, 
                proxy_addr TEXT,
                proxy_user TEXT, 
                proxy_pass TEXT, 
                seed_channel TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY, 
                setting_value TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS comments_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                profile_name TEXT,
                channel_id INTEGER,
                post_id INTEGER,
                comment_id INTEGER,
                timestamp_posted TIMESTAMP,
                status TEXT DEFAULT 'alive'
            )"""
        ]
        for q in queries: self._execute(q)

        migrations =[
            "ALTER TABLE profiles ADD COLUMN status TEXT DEFAULT 'idle'",
            "ALTER TABLE profiles ADD COLUMN target_channel TEXT DEFAULT ''",
            "ALTER TABLE profiles ADD COLUMN created_channel TEXT DEFAULT ''",
            "ALTER TABLE profiles ADD COLUMN last_error TEXT DEFAULT ''",
            "ALTER TABLE profiles ADD COLUMN first_name TEXT DEFAULT ''",
            "ALTER TABLE profiles ADD COLUMN last_name TEXT DEFAULT ''",
            "ALTER TABLE profiles ADD COLUMN bio TEXT DEFAULT ''",
            "ALTER TABLE profiles ADD COLUMN offer_text TEXT DEFAULT ''",
            "ALTER TABLE profiles ADD COLUMN funnel_mode TEXT DEFAULT 'direct'",
            "ALTER TABLE profiles ADD COLUMN channel_title TEXT DEFAULT ''",
            "ALTER TABLE profiles ADD COLUMN main_channel_title TEXT DEFAULT ''",
            "ALTER TABLE profiles ADD COLUMN create_main_channel INTEGER DEFAULT 0",
            "ALTER TABLE profiles ADD COLUMN warmup_count INTEGER DEFAULT 3",
            "ALTER TABLE profiles ADD COLUMN warmup_min INTEGER DEFAULT 5",
            "ALTER TABLE profiles ADD COLUMN warmup_max INTEGER DEFAULT 15",
            "ALTER TABLE profiles ADD COLUMN daily_limit INTEGER DEFAULT 15",
            "ALTER TABLE profiles ADD COLUMN delay_min INTEGER DEFAULT 5",
            "ALTER TABLE profiles ADD COLUMN delay_max INTEGER DEFAULT 15",
            "ALTER TABLE channels ADD COLUMN description TEXT DEFAULT ''",
            "ALTER TABLE channels ADD COLUMN ai_tags TEXT DEFAULT ''",
            "ALTER TABLE channels ADD COLUMN pos_x REAL DEFAULT 0.0",
            "ALTER TABLE channels ADD COLUMN pos_y REAL DEFAULT 0.0",
            "ALTER TABLE channels ADD COLUMN last_posts_raw TEXT DEFAULT ''",
            "ALTER TABLE channels ADD COLUMN proxy_name TEXT DEFAULT ''",
            "ALTER TABLE channels ADD COLUMN category TEXT DEFAULT 'Uncategorized'",
            "ALTER TABLE channels ADD COLUMN strike_count INTEGER DEFAULT 0",
            "ALTER TABLE channels ADD COLUMN whitelist_status TEXT DEFAULT 'neutral'",
            "ALTER TABLE profiles ADD COLUMN country_code TEXT DEFAULT ''",
            "ALTER TABLE profiles ADD COLUMN banned_at TIMESTAMP",
            "ALTER TABLE comments_history ADD COLUMN discussion_id INTEGER DEFAULT 0"
        ]
        for m in migrations:
            try: self._execute(m)
            except sqlite3.OperationalError: pass

        default_settings = {'min_subscribers': '500', 'max_depth': '15', 'delay_sec': '15', 'scan_mode': 'fast'}
        for k, v in default_settings.items():
            self._execute("INSERT OR IGNORE INTO app_settings (setting_key, setting_value) VALUES (?, ?)", (k, v))

        if self._execute("SELECT COUNT(*) FROM profiles", fetch=True)[0] == 0:
            self.create_profile("Profile_1")

    def get_global_settings(self):
        rows = self._execute("SELECT setting_key, setting_value FROM app_settings", fetchall=True)
        res = {}
        for k, v in rows:
            if v.isdigit(): res[k] = int(v)
            else: res[k] = v
        return res

    def update_global_settings(self, settings_dict):
        for k, v in settings_dict.items(): 
            query = "INSERT OR REPLACE INTO app_settings (setting_key, setting_value) VALUES (?, ?)"
            self._execute(query, (k, str(v)))

    def add_keywords_bulk(self, words_list, kw_type):
        query = "INSERT OR IGNORE INTO keywords (word, type, weight) VALUES (?, ?, 'medium')"
        with self._lock:
            with sqlite3.connect(self.db_name, timeout=20.0) as conn:
                conn.executemany(query,[(w, kw_type) for w in words_list])

    def get_all_keywords(self):
        return self._execute("SELECT word, type FROM keywords", fetchall=True) or[]

    def get_all_profiles(self):
        return self._execute("SELECT name, status, last_error, target_channel, created_channel FROM profiles ORDER BY id", fetchall=True)

    def get_profile(self, name):
        query = "SELECT * FROM profiles WHERE name = ?"
        with self._lock:
            with sqlite3.connect(self.db_name) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(query, (name,))
                row = cursor.fetchone()
                if row: return dict(row)
        return None

    def create_profile(self, name):
        try:
            self._execute("INSERT INTO profiles (name, proxy_type) VALUES (?, 'None')", (name,))
            return True
        except sqlite3.IntegrityError: return False

    def update_profile(self, name, data):
        query = "UPDATE profiles SET api_id=?, api_hash=?, proxy_type=?, proxy_addr=?, proxy_user=?, proxy_pass=?, seed_channel=? WHERE name=?"
        self._execute(query, (data.get('api_id', ''), data.get('api_hash', ''), data.get('proxy_type', 'None'), data.get('proxy_addr', ''), data.get('proxy_user', ''), data.get('proxy_pass', ''), data.get('seed_channel', ''), name))

    def update_profile_status(self, name, status, error=''):
        self._execute("UPDATE profiles SET status=?, last_error=? WHERE name=?", (status, error, name))

    def delete_profile(self, name):
        self._execute("DELETE FROM profiles WHERE name = ?", (name,))

    def log_comment(self, profile_name, channel_id, post_id, comment_id, discussion_id=0):
        now = datetime.datetime.now().isoformat()
        self._execute(
            "INSERT INTO comments_history (profile_name, channel_id, post_id, comment_id, discussion_id, timestamp_posted) VALUES (?, ?, ?, ?, ?, ?)",
            (profile_name, channel_id, post_id, comment_id, discussion_id, now)
        )

    def get_comments_to_check(self, profile_name):
        # Берем комменты, которым больше 2 часов
        threshold = (datetime.datetime.now() - datetime.timedelta(hours=2)).isoformat()
        query = "SELECT id, channel_id, discussion_id, comment_id FROM comments_history WHERE profile_name=? AND status='alive' AND timestamp_posted < ? LIMIT 5"
        return self._execute(query, (profile_name, threshold), fetchall=True)

    def process_comment_result(self, db_id, channel_id, is_survived):
        if is_survived:
            self._execute("UPDATE comments_history SET status='survived' WHERE id=?", (db_id,))
            self._execute("UPDATE channels SET whitelist_status='whitelist' WHERE telegram_id=?", (channel_id,))
        else:
            self._execute("UPDATE comments_history SET status='deleted' WHERE id=?", (db_id,))
            self._execute("UPDATE channels SET strike_count = strike_count + 1 WHERE telegram_id=?", (channel_id,))
            
            # Проверяем, не стал ли канал токсичным (3 страйка)
            row = self._execute("SELECT strike_count FROM channels WHERE telegram_id=?", (channel_id,), fetch=True)
            if row and row[0] >= 3:
                self._execute("UPDATE channels SET whitelist_status='toxic', status='rejected', description='ERR: Toxic (Auto-ban)' WHERE telegram_id=?", (channel_id,))

    def add_channel(self, telegram_id, username, title, description, subscribers, has_comments, status='queue', proxy_name=''):
        now = datetime.datetime.now().isoformat()
        with self._lock:
            with sqlite3.connect(self.db_name, timeout=20.0) as conn:
                cursor = conn.cursor()
                saved_tags = ""
                if telegram_id > 0 and username:
                    # Ищем фейковые дубли от веба (ID <= 0) с таким же username
                    cursor.execute("SELECT telegram_id, ai_tags FROM channels WHERE username = ? AND telegram_id <= 0", (username,))
                    fake_rows = cursor.fetchall()
                    for f_id, f_tags in fake_rows:
                        if f_tags: saved_tags = f_tags
                        cursor.execute("DELETE FROM channels WHERE telegram_id = ?", (f_id,))
                        
                query = """INSERT INTO channels (telegram_id, username, title, description, subscribers, has_comments, status, last_scraped, proxy_name) 
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(telegram_id) DO UPDATE SET 
                           username=excluded.username, title=excluded.title, description=excluded.description, 
                           subscribers=excluded.subscribers, has_comments=excluded.has_comments, last_scraped=excluded.last_scraped, proxy_name=excluded.proxy_name"""
                cursor.execute(query, (telegram_id, username, title, description, subscribers, has_comments, status, now, proxy_name))
                
                if telegram_id > 0 and username and saved_tags:
                    # Восстанавливаем теги ИИ, если они были у удаленного веб-дубля
                    cursor.execute("UPDATE channels SET ai_tags = ? WHERE telegram_id = ? AND (ai_tags IS NULL OR ai_tags = '')", (saved_tags, telegram_id))
                conn.commit()

    def update_channel_content(self, telegram_id, raw_text):
        self._execute("UPDATE channels SET last_posts_raw = ? WHERE telegram_id = ?", (raw_text, telegram_id))

    def get_next_channel_in_queue(self):
        import sqlite3
        with self._lock: # Жестко блокируем доступ для других потоков
            with sqlite3.connect(self.db_name, check_same_thread=False) as conn:
                cursor = conn.cursor()
                # 1. Ищем свободный канал
                cursor.execute("SELECT telegram_id, username FROM channels WHERE status = 'queue' LIMIT 1")
                row = cursor.fetchone()
                
                if row:
                    # 2. Мгновенно забираем его себе, пока лок не снят!
                    cursor.execute("UPDATE channels SET status = 'processing' WHERE telegram_id = ?", (row[0],))
                    conn.commit()
                    return {"telegram_id": row[0], "username": row[1]}
                    
        return None

    def update_channel_status(self, telegram_id, status, username=None):
        if telegram_id != 0: self._execute("UPDATE channels SET status = ? WHERE telegram_id = ?", (status, telegram_id))
        elif username: self._execute("UPDATE channels SET status = ? WHERE username = ?", (status, username))

    def add_graph_link(self, source_id, target_id, link_type):
        self._execute("INSERT OR IGNORE INTO graph_links (source_id, target_id, link_type) VALUES (?, ?, ?)", (source_id, target_id, link_type))

    def add_comment_for_review(self, channel_id, role, text, link):
        self._execute("INSERT OR IGNORE INTO comments_review (channel_id, role, text, link) VALUES (?, ?, ?, ?)", (channel_id, role, text, link))

    def dismiss_comment(self, link):
        self._execute("UPDATE comments_review SET status = 'reviewed' WHERE link = ?", (link,))

    def get_pending_comments(self):
        query = "SELECT c.title, cr.role, cr.text, cr.link FROM comments_review cr JOIN channels c ON cr.channel_id = c.telegram_id WHERE cr.status = 'pending' ORDER BY cr.id DESC LIMIT 50"
        return self._execute(query, fetchall=True)

    def get_statistics(self):
        return {
            "approved": self._execute("SELECT COUNT(*) FROM channels WHERE status IN ('approved', 'enriching')", fetch=True)[0],
            "rejected": self._execute("SELECT COUNT(*) FROM channels WHERE status = 'rejected'", fetch=True)[0],
            "queue": self._execute("SELECT COUNT(*) FROM channels WHERE status = 'queue'", fetch=True)[0],
            "comments_found": self._execute("SELECT COUNT(*) FROM comments_review WHERE status='pending'", fetch=True)[0]
        }

    def get_statistics_by_proxy(self):
        query = "SELECT proxy_name, SUM(CASE WHEN status IN ('approved', 'enriching') THEN 1 ELSE 0 END), SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END), SUM(CASE WHEN status = 'queue' THEN 1 ELSE 0 END), COUNT(*) FROM channels WHERE proxy_name != '' GROUP BY proxy_name ORDER BY COUNT(*) DESC"
        rows = self._execute(query, fetchall=True) or[]
        return [{"proxy_name": r[0], "approved": r[1], "rejected": r[2], "queue": r[3], "total": r[4]} for r in rows]

    def get_channels_for_ai_export(self):
        query = "SELECT telegram_id, username, title, IFNULL(description, ''), IFNULL(last_posts_raw, ''), ai_tags, has_comments FROM channels WHERE status IN ('approved', 'enriching')"
        return self._execute(query, fetchall=True)

    def update_channel_tags(self, telegram_id, tags):
        self._execute("UPDATE channels SET ai_tags = ? WHERE telegram_id = ?", (tags, telegram_id))

    def update_tags_by_username(self, username, tags):
        self._execute("UPDATE channels SET ai_tags = ? WHERE username = ?", (tags, username))

    def update_super_folders(self, mapping_dict):
        with self._lock:
            with sqlite3.connect(self.db_name, timeout=20.0) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT telegram_id, ai_tags FROM channels WHERE ai_tags IS NOT NULL AND ai_tags != ''")
                rows = cursor.fetchall()
                updates = []
                for tid, tags_str in rows:
                    channel_tags = [t.strip().lower() for t in tags_str.split(',')]
                    new_cat = None
                    for category, cat_tags in mapping_dict.items():
                        clean_cat_tags = [ct.strip().lower() for ct in cat_tags]
                        if any(t in clean_cat_tags for t in channel_tags):
                            new_cat = category
                            break
                    if new_cat:
                        updates.append((new_cat, tid))
                        
                if updates:
                    cursor.executemany("UPDATE channels SET category = ? WHERE telegram_id = ?", updates)
                conn.commit()

    def generate_semantic_links(self):
        with self._lock:
            with sqlite3.connect(self.db_name, timeout=20.0) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT category, telegram_id 
                    FROM channels 
                    WHERE status IN ('approved', 'enriching') 
                      AND category IS NOT NULL 
                      AND category != 'Uncategorized' 
                    ORDER BY subscribers DESC
                """)
                hubs = {}
                for row in cursor.fetchall():
                    cat, tid = row[0], row[1]
                    if cat not in hubs:
                        hubs[cat] = tid 
                cursor.execute("""
                    SELECT telegram_id, category
                    FROM channels c
                    WHERE status IN ('approved', 'enriching')
                      AND category IS NOT NULL 
                      AND category != 'Uncategorized'
                      AND NOT EXISTS (
                          SELECT 1 FROM graph_links gl 
                          WHERE gl.source_id = c.telegram_id OR gl.target_id = c.telegram_id
                      )
                """)
                isolated_channels = cursor.fetchall()
                new_links = []
                for tid, cat in isolated_channels:
                    hub_id = hubs.get(cat)
                    if hub_id and hub_id != tid:
                        new_links.append((hub_id, tid, 'ai_semantic'))
                        
                if new_links:
                    cursor.executemany("INSERT OR IGNORE INTO graph_links (source_id, target_id, link_type) VALUES (?, ?, ?)", new_links)
                conn.commit()

    def get_global_db_health(self):
        try:
            db_size_mb = os.path.getsize(self.db_name) / (1024 * 1024)
        except Exception:
            db_size_mb = 0.0

        stats = self._execute("""
            SELECT 
                COUNT(*) as total_channels,
                SUM(CASE WHEN status IN ('approved', 'enriching') THEN 1 ELSE 0 END) as approved_channels,
                SUM(CASE WHEN ai_tags LIKE '%#%' AND status IN ('approved', 'enriching') THEN 1 ELSE 0 END) as ai_tagged_channels
            FROM channels
        """, fetch=True)
        
        total_links_res = self._execute("SELECT COUNT(*) FROM graph_links", fetch=True)
        total_links = total_links_res[0] if total_links_res else 0
        
        return {
            "db_size_mb": round(db_size_mb, 2),
            "total_channels": stats[0] if stats and stats[0] else 0,
            "approved_channels": stats[1] if stats and stats[1] else 0,
            "ai_tagged_channels": stats[2] if stats and stats[2] else 0,
            "total_links": total_links
        }

    def get_full_graph_data(self):
        channels = self._execute("SELECT telegram_id, username, title, IFNULL(description, ''), ai_tags, subscribers FROM channels WHERE status IN ('approved', 'enriching')", fetchall=True)
        links = self._execute("SELECT source_id, target_id, link_type FROM graph_links", fetchall=True)
        return channels, links

    def update_coordinates_bulk(self, coords_dict):
        query = "UPDATE channels SET pos_x = ?, pos_y = ? WHERE telegram_id = ?"
        data = [(float(pos[0]), float(pos[1]), tid) for tid, pos in coords_dict.items()]
        with self._lock:
            with sqlite3.connect(self.db_name, timeout=20.0) as conn:
                conn.executemany(query, data)

    def get_incomplete_channels_stats(self):
        query = "SELECT COUNT(*) FROM channels WHERE (subscribers = 0 OR last_posts_raw = '' OR last_posts_raw IS NULL) AND status IN ('queue', 'approved', 'enriching')"
        res = self._execute(query, fetch=True)
        return res[0] if res else 0

    def get_all_incomplete_channels(self):
        # Просто берем список, не меняя статус массово. Статус будем менять поштучно в процессе.
        query = "SELECT telegram_id, username FROM channels WHERE (subscribers = 0 OR last_posts_raw = '' OR last_posts_raw IS NULL) AND status IN ('queue', 'approved', 'enriching')"
        rows = self._execute(query, fetchall=True)
        return [{"telegram_id": r[0], "username": r[1]} for r in (rows or [])]

    def update_enriched_channel(self, telegram_id, username, title, description, subscribers, has_comments, last_posts_raw):
        now = datetime.datetime.now().isoformat()
        if telegram_id != 0:
            query = """UPDATE channels SET 
                       title=?, description=?, subscribers=?, has_comments=?, last_posts_raw=?, status='approved', last_scraped=? 
                       WHERE telegram_id=?"""
            self._execute(query, (title, description, subscribers, has_comments, last_posts_raw, now, telegram_id))
        elif username:
            query = """UPDATE channels SET 
                       title=?, description=?, subscribers=?, has_comments=?, last_posts_raw=?, status='approved', last_scraped=? 
                       WHERE username=?"""
            self._execute(query, (title, description, subscribers, has_comments, last_posts_raw, now, username))

    def get_graph_render_data(self):
        query_nodes = "SELECT telegram_id, username, title, subscribers, pos_x, pos_y, ai_tags, IFNULL(last_posts_raw, ''), has_comments, category FROM channels WHERE status IN ('approved', 'enriching')"
        nodes = self._execute(query_nodes, fetchall=True)
        query_edges = "SELECT source_id, target_id, link_type FROM graph_links"
        edges = self._execute(query_edges, fetchall=True)
        return nodes, edges

    def import_external_leads(self, leads_list):
        query = """INSERT INTO channels (telegram_id, username, title, description, subscribers, has_comments, status, ai_tags, last_posts_raw, last_scraped) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(telegram_id) DO UPDATE SET 
                   title=excluded.title, 
                   description=CASE WHEN excluded.description != '' THEN excluded.description ELSE channels.description END, 
                   subscribers=CASE WHEN excluded.subscribers > 0 THEN excluded.subscribers ELSE channels.subscribers END, 
                   has_comments=excluded.has_comments, 
                   ai_tags=CASE WHEN excluded.ai_tags != '' THEN excluded.ai_tags ELSE channels.ai_tags END, 
                   last_posts_raw=CASE WHEN excluded.last_posts_raw != '' THEN excluded.last_posts_raw ELSE channels.last_posts_raw END, 
                   status=excluded.status"""
        data = []
        now = datetime.datetime.now().isoformat()
        
        for lead in leads_list:
            uname = lead.get('username', '')
            if not uname: continue
            
            existing = self._execute("SELECT telegram_id FROM channels WHERE username=?", (uname,), fetch=True)
            if existing:
                target_id = existing[0]
            else:
                target_id = -int(hashlib.md5(uname.encode('utf-8')).hexdigest()[:12], 16)
            
            data.append((
                target_id, uname, lead.get('title', 'Unknown'), lead.get('description', ''),
                lead.get('subscribers', 0), lead.get('has_comments', True), 'approved',
                lead.get('tags', ''), lead.get('last_posts', ''), now
            ))
            
        with self._lock:
            with sqlite3.connect(self.db_name, timeout=20.0) as conn:
                conn.executemany(query, data)

    def get_untagged_channels(self, limit=50):
        query = """SELECT telegram_id, username, title, IFNULL(description, ''), IFNULL(last_posts_raw, '') 
                   FROM channels 
                   WHERE status IN ('approved', 'enriching') 
                     AND (ai_tags IS NULL OR ai_tags = '' OR ai_tags = '[ОШИБКА_ИИ]' OR ai_tags NOT LIKE '%#%') 
                   ORDER BY (subscribers > 0) DESC, subscribers DESC
                   LIMIT ?"""
        return self._execute(query, (limit,), fetchall=True)

    def get_graph_folders(self):
        query = """
            SELECT category as folder_tag, COUNT(telegram_id) as ch_count, SUM(subscribers) as total_subs
            FROM channels
            WHERE status IN ('approved', 'enriching') AND category IS NOT NULL AND category != 'Uncategorized'
            GROUP BY category ORDER BY total_subs DESC
        """
        return self._execute(query, fetchall=True)

    def get_folder_edges(self):
        query = """
            SELECT c1.category as src_folder, c2.category as tgt_folder, COUNT(*) as weight
            FROM graph_links gl
            JOIN channels c1 ON gl.source_id = c1.telegram_id
            JOIN channels c2 ON gl.target_id = c2.telegram_id
            WHERE src_folder != tgt_folder 
              AND src_folder != 'Uncategorized' AND tgt_folder != 'Uncategorized'
              AND src_folder IS NOT NULL AND tgt_folder IS NOT NULL
            GROUP BY src_folder, tgt_folder
        """
        return self._execute(query, fetchall=True)

    def get_available_tags_for_ai(self):
        query = "SELECT category, ai_tags FROM channels WHERE status IN ('approved', 'enriching') AND has_comments = 1"
        rows = self._execute(query, fetchall=True)
        unique_categories = set()
        tag_counts = {}
        
        for cat, tags in rows:
            if cat and cat != 'Uncategorized':
                unique_categories.add(cat)
            if tags:
                parts = [t.strip() for t in tags.split(',')]
                for p in parts:
                    if p.startswith('#'):
                        tag_counts[p] = tag_counts.get(p, 0) + 1
                        
        # Берем только топ-50 самых популярных тегов, чтобы не перегружать ИИ
        sorted_tags = sorted(tag_counts.keys(), key=lambda k: tag_counts[k], reverse=True)[:50]
        return list(unique_categories), sorted_tags

    def get_channels_by_tags_for_ai(self, ai_selected_tags, min_subs=0, max_subs=999999999):
        if not ai_selected_tags:
            return []
            
        with self._lock:
            with sqlite3.connect(self.db_name, timeout=20.0) as conn:
                cursor = conn.cursor()
                
                conditions = []
                params = []
                for tag in ai_selected_tags:
                    conditions.append("(ai_tags LIKE ? OR category LIKE ?)")
                    params.extend([f"%{tag}%", f"%{tag}%"])
                    
                where_clause = " OR ".join(conditions)
                params.extend([min_subs, max_subs])
                
                query = f"""
                    SELECT telegram_id, username, title, subscribers, category, ai_tags, IFNULL(last_posts_raw, '')
                    FROM channels 
                    WHERE status IN ('approved', 'enriching') AND has_comments = 1 
                      AND ({where_clause})
                      AND subscribers >= ? AND subscribers <= ?
                    ORDER BY subscribers DESC
                    LIMIT 100
                """
                cursor.execute(query, params)
                return cursor.fetchall()