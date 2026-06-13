# PROJECT CONTEXT
Type: LEGAL_BLOG
Stack: Vanilla HTML/CSS/JS (GitHub Pages) + Python Telegram Bot (python-telegram-bot v20)
Goal: Avukat Kurt için hukuk blogu — Telegram botla yazı yayınlanır, GitHub Pages'da gösterilir
Owner: Kurt (erdemkapkara)
Deploy: GitHub Pages (site) + Railway (bot)
Repo: erdemkapkara/Kurt

# ARCHITECTURE
- `index.html`   → tek sayfalık blog sitesi, posts.json'ı fetch eder
- `posts.json`   → tüm yazıları tutar (GitHub API üzerinden güncellenir)
- `bot/bot.py`   → Telegram botu: yazı al → parse et → onay iste → GitHub'a yaz
- `Procfile`     → Railway için başlatma komutu
- `Dockerfile`   → konteyner dağıtımı
- `requirements.txt` → Python bağımlılıkları

# AGENT ROLES
- orchestrator: planlar, sub-task'ları delege eder, çıktıyı review eder
- coder: bot.py ve index.html'e kod yazar
- styler: index.html'deki CSS değişkenlerini ve tasarım tokenlarını yönetir
- reviewer: kod ve UI'yi kontrol eder, hataları işaretler
- tester: Puppeteer ile siteyi açar, Python syntax kontrol eder, posts.json şemasını doğrular

# ENVIRONMENT VARIABLES (Railway'de tanımlı)
- TELEGRAM_TOKEN   → @BotFather'dan alınan bot token'ı
- GITHUB_TOKEN     → repo:* yetkili Personal Access Token
- GITHUB_REPO      → erdemkapkara/Kurt
- ALLOWED_USER_ID  → izinli ek Telegram kullanıcı ID'leri (virgülle ayrılmış)
# Hardcoded izinli ID'ler: 7284939267, 8092559336

# RULES
- Python: tip bildirimi yok, async/await doğru kullan, python-telegram-bot v20 API'si
- HTML/CSS/JS: tek dosya (index.html), inline style yok, CSS değişkenleri kullan
- posts.json formatı: {id, featured, title, category, excerpt, date, readTime, content(HTML)}
- Kategoriler: Ceza Hukuku · Mali Hukuk · Aile Hukuku · İdare Hukuku
- Commit: her tamamlanan özellik sonrası commit at
- GitHub API: tüm posts.json okuma/yazma işlemleri GitHub Contents API üzerinden

# FILE STRUCTURE
/             → index.html, posts.json, Dockerfile, Procfile, requirements.txt
/bot          → bot.py, .env.example, KURULUM.md
/.claude      → settings.json, settings.local.json

# DONE = DEFINITION
- Bot hatasız çalışıyor (python bot/bot.py)
- Site GitHub Pages'da render ediliyor
- Mobil görünüm bozulmuyor
- posts.json şemasına uygun yazı ekleniyor
- Git'e commit edilmiş

# MODEL STRATEJİSİ
| Ajan        | Model                | Neden                        |
|-------------|----------------------|------------------------------|
| Orchestrator | claude-sonnet-4-6   | Planlama ve karar verme      |
| Coder       | claude-haiku-4-5     | Tekrarlayan kod yazımı       |
| Reviewer    | claude-haiku-4-5     | Basit kontrol                |
| Tester      | claude-haiku-4-5     | Puppeteer + syntax kontrol   |

# MCP SERVERS
- github     → repo yönetimi, issue/PR, git push (GITHUB_PERSONAL_ACCESS_TOKEN env var gerekli)
- puppeteer  → headless Chrome ile UI testi (Chrome: ~/.cache/puppeteer/chrome/win64-131.0.6778.204)

# TESTER AGENT PROMPT ŞABLONU
```
Sen Kurt projesinin test ajanısın. Puppeteer MCP ve aşağıdaki kontrolleri kullan.

KONTROL LİSTESİ:
1. [PYTHON SYNTAX] `python -m py_compile bot/bot.py` — hata çıkmamalı
2. [JSON SCHEMA] posts.json oku — her obje {id, featured, title, category, excerpt, date, readTime, content} alanlarına sahip olmalı
3. [UI - opsiyonel] Eğer local server çalışıyorsa Puppeteer ile http://localhost:PORT aç:
   - Sayfa yüklenme hatası var mı? (console errors)
   - Mobil viewport (375px) kırılıyor mu?
   - Kartlar render ediliyor mu?

ÇIKTI FORMAT:
[PASS] ✅ veya [FAIL] ❌ — sebep
Her kontrol için ayrı satır.
```

# ORCHESTRATOR PROMPT ŞABLONU
```
Sen Kurt projesinin geliştirme orkestratörüsün.
GÖREV: [GÖREV_AÇIKLAMASI]

ÇALIŞMA PROTOKOLÜ:
1. Önce CLAUDE.md oku
2. Görevi sub-task'lara böl
3. Her task için sub-agent başlat; sadece ilgili dosyaları ver
4. Çıktıyı review et, hata varsa düzelt
5. Bitti → commit et

TOKEN KURALI:
- Sub-agent'a sadece ilgili dosyaları ver
- Genel context aktarma, CLAUDE.md'e referans ver

SUB-AGENT FORMAT:
<task>[görev adı]</task>
<context>[sadece bu task için gereken şey — ilgili dosya parçaları]</context>
<output>[ne üretmeli]</output>
<model>haiku</model>

BAŞLA. Adımları listele, onay bekleme, direkt çalış.
```
