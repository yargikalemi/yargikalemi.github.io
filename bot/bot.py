import os
import json
import base64
import re
import logging
from datetime import datetime
import requests
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = os.getenv('TELEGRAM_TOKEN', '')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', '')
REPO = os.getenv('GITHUB_REPO', 'yargikalemi/yargikalemi.github.io')
ALLOWED_IDS = {7284939267, 8092559336, 8855943051} | set(
    int(x.strip()) for x in os.getenv('ALLOWED_USER_ID', '').split(',') if x.strip().isdigit()
)

MONTHS = ['', 'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
          'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']

CATEGORY_KEYWORDS = {
    'Ceza Hukuku':              ['gözaltı', 'tutuklama', 'suç', 'hapis', 'ceza', 'sanık', 'beraat',
                                  'savcı', 'kovuşturma', 'soruşturma', 'adli', 'cezai', 'iddianame',
                                  'susma', 'ifade', 'zamanaşımı'],
    'Ticaret Hukuku':           ['ticaret', 'şirket', 'ticari', 'ortaklık', 'hisse', 'tacir',
                                  'ticaret sicili', 'limited', 'anonim', 'ticari uyuşmazlık'],
    'Tüketici Hukuku':          ['tüketici', 'ayıplı', 'iade', 'garanti', 'satın alma', 'sipariş',
                                  'tüketim', 'üretici', 'satıcı', 'hakkaniyetsiz şart'],
    'Medeni Hukuk':             ['mülkiyet', 'eşya', 'hak', 'medeni', 'kişilik', 'vasiyet', 'vasi'],
    'Aile Hukuku':              ['boşanma', 'nafaka', 'velayet', 'evlilik', 'çocuk', 'miras',
                                  'aile', 'eş', 'nişan', 'evlat', 'mal paylaşımı'],
    'Ceza Muhakemeleri Hukuku': ['muhakeme', 'yargılama', 'delil', 'itiraz', 'kanun yolu', 'temyiz',
                                  'istinaf', 'uzlaşma', 'duruşma', 'müdafi', 'savunma'],
    'İdare Hukuku':             ['idare', 'devlet', 'belediye', 'kamu', 'ihale', 'disiplin',
                                  'memur', 'yönetim', 'bakanlık', 'kurum', 'iptal', 'danıştay'],
    'Borçlar Hukuku':           ['borç', 'alacak', 'sözleşme', 'tazminat', 'haksız fiil', 'edim',
                                  'ifa', 'borca aykırılık', 'zarar'],
    'KVKK':                     ['kvkk', 'kişisel veri', 'gizlilik', 'veri koruma', 'gdpr',
                                  'veri ihlali', 'aydınlatma yükümlülüğü', 'açık rıza'],
    'Gayrimenkul / Kira':       ['kira', 'kiracı', 'ev sahibi', 'gayrimenkul', 'tapu',
                                  'kat mülkiyeti', 'irtifak', 'ipotek', 'kira artışı'],
    'İcra ve İflas':            ['icra', 'iflas', 'haciz', 'konkordato', 'borçlu',
                                  'icra takibi', 'ödeme emri'],
    'Anayasa Mahkemesi':        ['anayasa', 'bireysel başvuru', 'temel hak', 'anayasa mahkemesi',
                                  'özgürlük', 'hak ihlali'],
    'AİHM':                     ['aihm', 'avrupa', 'insan hakları mahkemesi', 'strasbourg',
                                  'avrupa insan', 'avrupa sözleşmesi'],
}

# Onay bekleyen yazılar
pending = {}
pending_edit = {}

HELP_TEXT = (
    "👨‍⚖️ *Yargı Kalemi Blog Botu*\n\n"
    "Herhangi bir yazı gönder — başlık, kategori ve özeti otomatik çıkarırım, "
    "onayını aldıktan sonra yayınlarım.\n\n"
    "📷 *Fotoğraflı yazı:* Fotoğraf gönder, açıklamaya yazıyı yaz.\n\n"
    "*Yapılandırılmış format:*\n"
    "```\n"
    "Başlık: Yazı başlığı\n"
    "Kategori: Ceza Hukuku\n"
    "Özet: Kısa açıklama\n\n"
    "Yazı içeriği...\n"
    "```\n\n"
    "*Kategoriler:*\n"
    "Ceza Hukuku · Ticaret Hukuku · Tüketici Hukuku · Medeni Hukuk · Aile Hukuku\n"
    "Ceza Muhakemeleri Hukuku · İdare Hukuku · Borçlar Hukuku · KVKK\n"
    "Gayrimenkul / Kira · İcra ve İflas · Anayasa Mahkemesi · AİHM\n\n"
    "*Komutlar:*\n"
    "/liste — yayındaki yazılar (ID numaralarıyla)\n"
    "/sil 3 — 3 numaralı yazıyı sil\n"
    "/duzenle 3 — 3 numaralı yazıyı güncelle\n"
    "/onecikart 3 — 3 numaralı yazıyı öne çıkar\n"
    "/migrate — eski yazı ID'lerini 1\\-2\\-3 formatına çevir\n"
    "/iptal — düzenlemeyi iptal et"
)


# ── GitHub API ──────────────────────────────────────────────────────────────

def upload_image(data: bytes, filename: str) -> str:
    url = f"https://api.github.com/repos/{REPO}/contents/images/{filename}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    res = requests.get(url, headers=headers, timeout=15)
    sha = res.json().get('sha') if res.status_code == 200 else None
    payload = {"message": f"Görsel: {filename}", "content": base64.b64encode(data).decode()}
    if sha:
        payload["sha"] = sha
    res = requests.put(url, headers=headers, json=payload, timeout=30)
    if res.status_code not in (200, 201):
        msg = res.json().get('message', res.text[:100]) if res.content else ''
        raise Exception(f"GitHub görsel hatası: {res.status_code} — {msg}")
    return f"https://raw.githubusercontent.com/{REPO}/main/images/{filename}"


def get_posts():
    import time
    url = f"https://api.github.com/repos/{REPO}/contents/posts.json"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    for attempt in range(3):
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            break
        if attempt < 2:
            time.sleep(2)
    else:
        raise Exception(f"GitHub okuma hatası: {res.status_code}")
    data = res.json()
    content = base64.b64decode(data['content']).decode('utf-8')
    return json.loads(content), data['sha']


def renumber(posts):
    for i, p in enumerate(posts, 1):
        p['id'] = str(i)
    return posts


def save_posts(posts, sha, title):
    renumber(posts)
    url = f"https://api.github.com/repos/{REPO}/contents/posts.json"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json"}
    encoded = base64.b64encode(
        json.dumps(posts, ensure_ascii=False, indent=2).encode('utf-8')
    ).decode('utf-8')
    res = requests.put(url, headers=headers,
                       json={"message": f"Yeni yazı: {title}", "content": encoded, "sha": sha},
                       timeout=15)
    if res.status_code not in (200, 201):
        raise Exception(f"GitHub yazma hatası: {res.status_code}")


def move_to_trash(posts):
    """Silinen yazıları trash.json'a taşı (admin panelindeki çöp kutusuyla ortak)."""
    import time
    url = f"https://api.github.com/repos/{REPO}/contents/trash.json"
    headers = {"Authorization": f"token {GITHUB_TOKEN}", "Content-Type": "application/json"}
    res = requests.get(url, headers=headers, timeout=15)
    if res.status_code == 200:
        data = res.json()
        try:
            items = json.loads(base64.b64decode(data['content']).decode('utf-8'))
        except Exception:
            items = []
        sha = data['sha']
    else:
        items, sha = [], None
    now = datetime.now().isoformat()
    stamped = [{**p, "_tid": f"{int(datetime.now().timestamp()*1000)}-{i}", "deletedAt": now}
               for i, p in enumerate(posts)]
    encoded = base64.b64encode(
        json.dumps(stamped + items, ensure_ascii=False, indent=2).encode('utf-8')
    ).decode('utf-8')
    payload = {"message": f"Çöpe taşındı: {len(posts)} yazı", "content": encoded}
    if sha:
        payload["sha"] = sha
    requests.put(url, headers=headers, json=payload, timeout=15)


# ── Yazı ayrıştırma ─────────────────────────────────────────────────────────

def detect_category(text):
    text_lower = text.lower()
    scores = {cat: sum(1 for kw in kws if kw in text_lower)
              for cat, kws in CATEGORY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'Ceza Hukuku'


def text_to_html(text):
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    return ''.join(f'<p>{p.replace(chr(10), " ")}</p>' for p in paragraphs)


def make_slug(title):
    tr = str.maketrans('çğıöşüÇĞİÖŞÜ', 'cgiosuCGIOSU')
    slug = title.translate(tr).lower()
    return re.sub(r'[^a-z0-9]+', '-', slug)[:80].strip('-')


CAT_IMG_MAP = {'Ceza Hukuku': 'cezahukuku.jpg', 'İdare Hukuku': 'idarehukuku.jpeg'}
DEFAULT_POST_IMG = 'yazifoto.jpg'

_POST_TEMPLATE = """\
<!DOCTYPE html>
<html lang="tr" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>%%TITLE%% — Yargı Kalemi</title>
<meta name="description" content="%%EXCERPT%%">
<meta property="og:title" content="%%TITLE%%">
<meta property="og:description" content="%%EXCERPT%%">
<meta property="og:image" content="https://yargikalemi.github.io/%%IMG_URL%%">
<meta property="og:url" content="%%PAGE_URL%%">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Yargı Kalemi">
<meta name="twitter:card" content="summary_large_image">
<link rel="canonical" href="%%PAGE_URL%%">
<link rel="icon" type="image/png" href="../logo1.png">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,500;0,700;0,900;1,500&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
:root{--bg:#F7F5F0;--bg-card:#fff;--accent:#0D9488;--accent-h:#0F766E;--text:#1A2B3C;--text2:#4A5568;--text3:#8896A4;--border:#E0DBD3;--nav-bg:#fff}
[data-theme="dark"]{--bg:#0D1B2A;--bg-card:#112236;--accent:#2DD4BF;--accent-h:#5EEAD4;--text:#E8E4DC;--text2:#9EB0C2;--text3:#5E7287;--border:#1C3148;--nav-bg:#091524}
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
html{font-size:16px;scroll-behavior:smooth}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--text);line-height:1.65;transition:background .25s,color .25s}
#prog{position:fixed;top:0;left:0;height:3px;width:0;background:linear-gradient(90deg,var(--accent),var(--accent-h));z-index:999;transition:width .1s linear}
#hdr{position:sticky;top:0;z-index:200;background:var(--nav-bg);border-bottom:1px solid var(--border);transition:background .25s,border-color .25s}
.hdr-in{max-width:900px;margin:0 auto;display:flex;align-items:center;padding:0 1.5rem;height:58px;gap:1rem}
.back-lnk{display:flex;align-items:center;gap:.5rem;color:var(--accent);font-size:.86rem;font-weight:600;text-decoration:none;transition:color .2s}
.back-lnk:hover{color:var(--accent-h)}
.back-lnk i{font-size:.78rem}
.hdr-spacer{flex:1}
.theme-btn{width:34px;height:34px;border-radius:50%;background:none;border:1.5px solid var(--border);color:var(--text3);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:.82rem;transition:all .2s}
.theme-btn:hover{border-color:var(--accent);color:var(--accent);background:rgba(13,148,136,.06)}
.wrap{max-width:760px;margin:0 auto;padding:3rem 1.5rem 5rem}
.post-cat-badge{display:inline-flex;align-items:center;padding:.28rem .75rem;background:rgba(13,148,136,.1);color:var(--accent);border-radius:99px;font-size:.73rem;font-weight:700;letter-spacing:.05em;text-transform:uppercase;margin-bottom:1.15rem}
[data-theme="dark"] .post-cat-badge{background:rgba(45,212,191,.12)}
h1.post-title{font-family:'Playfair Display',serif;font-size:2.3rem;font-weight:900;line-height:1.2;color:var(--text);margin-bottom:1.1rem;letter-spacing:-.01em}
.post-meta{display:flex;flex-wrap:wrap;gap:.6rem 1.2rem;align-items:center;font-size:.82rem;color:var(--text3);padding-bottom:1.5rem;border-bottom:1px solid var(--border);margin-bottom:1.75rem}
.post-meta span{display:flex;align-items:center;gap:.35rem}
.cover-img{width:100%;max-height:440px;object-fit:cover;border-radius:10px;margin-bottom:2.5rem;display:block;box-shadow:0 8px 32px rgba(0,0,0,.1)}
.post-body{font-size:1.06rem;line-height:1.9;color:var(--text2)}
.post-body>*+*{margin-top:1rem}
.post-body h2{font-family:'Playfair Display',serif;font-size:1.55rem;font-weight:700;color:var(--text);margin-top:2.5rem;margin-bottom:.75rem;padding-bottom:.45rem;border-bottom:2px solid var(--border);line-height:1.3}
.post-body h3{font-family:'Playfair Display',serif;font-size:1.25rem;font-weight:700;color:var(--text);margin-top:2rem;margin-bottom:.6rem;line-height:1.35}
.post-body ul,.post-body ol{padding-left:1.65rem}
.post-body li{margin-bottom:.45rem}
.post-body blockquote{border-left:4px solid var(--accent);padding:.85rem 1.4rem;background:rgba(13,148,136,.05);margin:1.75rem 0;border-radius:0 8px 8px 0}
[data-theme="dark"] .post-body blockquote{background:rgba(45,212,191,.06)}
.post-body blockquote p{font-style:italic;font-size:1.05rem;color:var(--text2);margin:0}
.post-body a{color:var(--accent);text-decoration:underline;text-underline-offset:3px;text-decoration-thickness:1px}
.post-body a:hover{color:var(--accent-h)}
.post-body strong{font-weight:700;color:var(--text)}
.post-body table{width:100%;border-collapse:collapse;font-size:.93rem;margin:1.5rem 0}
.post-body th,.post-body td{padding:.6rem .9rem;border:1px solid var(--border);text-align:left}
.post-body th{background:rgba(13,148,136,.07);font-weight:700;color:var(--text)}
.post-body img{width:100%;border-radius:6px}
.post-body hr{border:none;border-top:2px solid var(--border);margin:2.5rem 0}
.share-wrap{margin-top:3.5rem;padding-top:2rem;border-top:1px solid var(--border)}
.share-label{font-size:.75rem;font-weight:700;color:var(--text3);text-transform:uppercase;letter-spacing:.07em;margin-bottom:.9rem}
.share-row{display:flex;gap:.5rem;flex-wrap:wrap}
.sbtn{display:inline-flex;align-items:center;gap:.42rem;padding:.5rem .95rem;border-radius:99px;font-size:.81rem;font-weight:600;cursor:pointer;border:none;transition:all .2s;font-family:'Inter',sans-serif}
.sbtn.tw{background:#1D9BF0;color:#fff}.sbtn.tw:hover{background:#1a8cd8;transform:translateY(-1px)}
.sbtn.wa{background:#25D366;color:#fff}.sbtn.wa:hover{background:#20b858;transform:translateY(-1px)}
.sbtn.cp{background:var(--bg-card);color:var(--text2);border:1.5px solid var(--border)}.sbtn.cp:hover{border-color:var(--accent);color:var(--accent);transform:translateY(-1px)}
.copy-ok{font-size:.79rem;color:var(--accent);font-weight:600;margin-top:.6rem;display:none}
.copy-ok.show{display:block}
.back-all{display:inline-flex;align-items:center;gap:.5rem;margin-top:2.5rem;padding:.6rem 1.25rem;background:var(--bg-card);border:1.5px solid var(--border);border-radius:99px;color:var(--text2);font-size:.85rem;font-weight:600;text-decoration:none;transition:all .2s}
.back-all:hover{border-color:var(--accent);color:var(--accent);transform:translateY(-1px)}
footer{background:var(--nav-bg);border-top:1px solid var(--border);padding:1.6rem 1.5rem;text-align:center;font-size:.79rem;color:var(--text3);line-height:1.7}
footer a{color:var(--accent);font-weight:600;text-decoration:none}
#go-top{position:fixed;bottom:1.6rem;right:1.6rem;width:44px;height:44px;border-radius:50%;background:var(--accent);color:#fff;border:none;cursor:pointer;font-size:.9rem;display:none;align-items:center;justify-content:center;box-shadow:0 4px 16px rgba(13,148,136,.35);z-index:100;transition:all .2s}
#go-top.vis{display:flex}
#go-top:hover{background:var(--accent-h);transform:translateY(-2px)}
@media(max-width:640px){.wrap{padding:2rem 1.1rem 3.5rem}h1.post-title{font-size:1.7rem}.post-body{font-size:.98rem}.hdr-in{padding:0 1rem}}
</style>
</head>
<body>
<div id="prog"></div>
<header id="hdr">
  <div class="hdr-in">
    <a href="../index.html" class="back-lnk"><i class="fas fa-arrow-left"></i>&nbsp;Yargı Kalemi</a>
    <div class="hdr-spacer"></div>
    <button class="theme-btn" id="theme-btn" aria-label="Tema"><i class="fas fa-moon"></i></button>
  </div>
</header>
<main>
  <div class="wrap">
    <div class="post-cat-badge">%%CATEGORY%%</div>
    <h1 class="post-title">%%TITLE%%</h1>
    <div class="post-meta">
      <span><i class="far fa-calendar-alt"></i>&nbsp;%%DATE%%</span>
      <span><i class="far fa-clock"></i>&nbsp;%%READTIME%% dk okuma</span>
    </div>
    <img class="cover-img" src="%%IMG_SRC%%" alt="%%TITLE%%" onerror="this.remove()">
    <div class="post-body">%%CONTENT%%</div>
    <div class="share-wrap">
      <div class="share-label">Bu yazıyı paylaş</div>
      <div class="share-row">
        <button class="sbtn tw" onclick="shr('tw')"><i class="fab fa-twitter"></i> Twitter / X</button>
        <button class="sbtn wa" onclick="shr('wa')"><i class="fab fa-whatsapp"></i> WhatsApp</button>
        <button class="sbtn cp" onclick="cp()"><i class="fas fa-link"></i> Linki Kopyala</button>
      </div>
      <div class="copy-ok" id="copy-ok">&#10003; Bağlantı kopyalandı!</div>
    </div>
    <a href="../index.html#posts" class="back-all"><i class="fas fa-arrow-left"></i> Tüm Yazılara Dön</a>
  </div>
</main>
<footer>
  <a href="../index.html">Yargı Kalemi</a> — Bu site hukuki danışmanlık hizmeti değildir; yalnızca bilgi amaçlıdır.<br>
  © 2025 Tüm Hakları Saklıdır
</footer>
<button id="go-top" onclick="scrollTo({top:0,behavior:'smooth'})" aria-label="Başa dön"><i class="fas fa-arrow-up"></i></button>
<script>
var PU=%%PAGE_URL_JS%%,PT=%%PAGE_TITLE_JS%%;
var html=document.documentElement,tb=document.getElementById('theme-btn');
if(localStorage.getItem('yk_theme')==='dark'){html.dataset.theme='dark';tb.innerHTML='<i class="fas fa-sun"></i>';}
tb.addEventListener('click',function(){var d=html.dataset.theme==='dark';html.dataset.theme=d?'light':'dark';tb.innerHTML=d?'<i class="fas fa-moon"></i>':'<i class="fas fa-sun"></i>';localStorage.setItem('yk_theme',d?'light':'dark');});
var prog=document.getElementById('prog'),gt=document.getElementById('go-top');
window.addEventListener('scroll',function(){var s=window.scrollY,t=document.documentElement.scrollHeight-window.innerHeight;prog.style.width=(t>0?(s/t*100):0)+'%';gt.classList.toggle('vis',s>380);},{passive:true});
function shr(p){var u=encodeURIComponent(PU),t=encodeURIComponent(PT);var m={tw:'https://twitter.com/intent/tweet?text='+t+'&url='+u,wa:'https://wa.me/?text='+encodeURIComponent(PT+' '+PU)};window.open(m[p],'_blank');}
function cp(){navigator.clipboard.writeText(PU).then(function(){var el=document.getElementById('copy-ok');el.classList.add('show');setTimeout(function(){el.classList.remove('show');},2500);});}
</script>
</body>
</html>"""


def _he(s):
    return str(s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def build_post_html(post):
    slug = post.get('slug') or make_slug(post.get('title', ''))
    raw_img = post.get('image') or CAT_IMG_MAP.get(post.get('category', ''), DEFAULT_POST_IMG)
    img_src = raw_img if raw_img.startswith('http') else '../' + raw_img
    img_url = raw_img if raw_img.startswith('http') else raw_img
    page_url = f'https://yargikalemi.com/posts/{slug}.html'
    page_title = post.get('title', '') + ' — Yargı Kalemi'
    content = post.get('content') or f'<p>{_he(post.get("excerpt", ""))}</p>'
    return (_POST_TEMPLATE
        .replace('%%TITLE%%', _he(post.get('title', '')))
        .replace('%%EXCERPT%%', _he(post.get('excerpt', '')))
        .replace('%%CATEGORY%%', _he(post.get('category', '')))
        .replace('%%DATE%%', _he(post.get('date', '')))
        .replace('%%READTIME%%', _he(str(post.get('readTime', ''))))
        .replace('%%IMG_SRC%%', img_src)
        .replace('%%IMG_URL%%', img_url)
        .replace('%%PAGE_URL%%', _he(page_url))
        .replace('%%CONTENT%%', content)
        .replace('%%PAGE_URL_JS%%', json.dumps(page_url))
        .replace('%%PAGE_TITLE_JS%%', json.dumps(page_title))
    )


def save_post_page(post):
    slug = post.get('slug') or make_slug(post.get('title', ''))
    if not slug:
        return
    url = f'https://api.github.com/repos/{REPO}/contents/posts/{slug}.html'
    headers = {'Authorization': f'token {GITHUB_TOKEN}', 'Content-Type': 'application/json'}
    get_res = requests.get(url, headers=headers, timeout=15)
    sha = get_res.json().get('sha') if get_res.status_code == 200 else None
    html_bytes = build_post_html(post).encode('utf-8')
    payload = {
        'message': f'Yazı sayfası: {post.get("title", "")}',
        'content': base64.b64encode(html_bytes).decode()
    }
    if sha:
        payload['sha'] = sha
    res = requests.put(url, headers=headers, json=payload, timeout=30)
    if res.status_code not in (200, 201):
        raise Exception(f'Sayfa oluşturma hatası HTTP {res.status_code}: {res.text[:200]}')


def build_post(title, category, excerpt, content_raw):
    now = datetime.now()
    return {
        "id": make_slug(title),
        "slug": make_slug(title),
        "featured": False,
        "title": title,
        "category": category,
        "excerpt": excerpt,
        "date": f"{now.day} {MONTHS[now.month]} {now.year}",
        "readTime": f"{max(1, round(len(content_raw.split()) / 200))} dk",
        "content": text_to_html(content_raw) or f"<p>{excerpt}</p>"
    }


def parse_structured(text):
    """Başlık/Kategori/Özet formatı."""
    title_m = re.search(r'Başlık:\s*(.+)', text)
    cat_m   = re.search(r'Kategori:\s*(.+)', text)
    exc_m   = re.search(r'Özet:\s*(.+)', text)
    if not (title_m and cat_m and exc_m):
        return None
    headers_end = max(title_m.end(), cat_m.end(), exc_m.end())
    content_raw = text[headers_end:].strip()
    return build_post(title_m.group(1).strip(),
                      cat_m.group(1).strip(),
                      exc_m.group(1).strip(),
                      content_raw)


def parse_auto(text):
    """Serbest metin → otomatik ayrıştırma."""
    paragraphs = [p.strip() for p in text.strip().split('\n\n') if p.strip()]
    if not paragraphs:
        return None

    # İlk paragraf kısa ise başlık, değilse ilk cümle başlık
    if len(paragraphs[0]) <= 120:
        title = paragraphs[0]
        content_paragraphs = paragraphs[1:]
    else:
        first_sentence = re.split(r'[.!?]\s', paragraphs[0])[0]
        title = first_sentence[:100].strip()
        content_paragraphs = paragraphs

    content_raw = '\n\n'.join(content_paragraphs)
    excerpt_raw = content_paragraphs[0] if content_paragraphs else title
    excerpt = excerpt_raw[:280] + ('…' if len(excerpt_raw) > 280 else '')
    category = detect_category(text)

    return build_post(title, category, excerpt, content_raw)


def confirm_keyboard():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yayınla", callback_data="confirm"),
        InlineKeyboardButton("✏️ Düzenle", callback_data="edit"),
        InlineKeyboardButton("❌ İptal",  callback_data="cancel"),
    ]])


# ── Fotoğraflı mesaj ────────────────────────────────────────────────────────

async def handle_photo(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return
    caption = (update.message.caption or '').strip()
    if not caption:
        await update.message.reply_text("📷 Fotoğrafla birlikte yazı metnini de gönder (caption olarak).")
        return

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    data = bytes(await file.download_as_bytearray())
    filename = f"{make_slug(caption[:40])}-{photo.file_unique_id}.jpg"

    try:
        image_url = upload_image(data, filename)
    except Exception as e:
        await update.message.reply_text(f"❌ Görsel yüklenemedi: {e}")
        return

    post = parse_structured(caption) or parse_auto(caption)
    if not post or not post.get('title'):
        await update.message.reply_text("❌ Yazı çok kısa. Daha uzun bir metin ekle.")
        return

    post['image'] = image_url
    pending[update.effective_user.id] = post

    preview = (
        f"📝 *Şu şekilde yayınlayayım mı?*\n\n"
        f"🖼️ *Görsel:* ✓ Yüklendi\n"
        f"📌 *Başlık:* {post['title']}\n"
        f"🏷️ *Kategori:* {post['category']}\n"
        f"⏱️ *Okuma süresi:* {post['readTime']}\n"
        f"📅 *Tarih:* {post['date']}\n\n"
        f"📋 *Özet:*\n{post['excerpt']}"
    )
    await update.message.reply_text(preview, parse_mode='Markdown', reply_markup=confirm_keyboard())


# ── Komutlar ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return
    await update.message.reply_text(HELP_TEXT, parse_mode='Markdown')


def liste_message(posts):
    lines = [f"📋 *Yayındaki Yazılar ({len(posts)})*\n"]
    keyboard = []
    for p in posts:
        star = "⭐ " if p.get('featured') else ""
        lines.append(f"{star}*{p['id']}* — {p['title']}")
        row = [InlineKeyboardButton(f"🗑 {p['id']}. Sil", callback_data=f"del_{p['id']}")]
        if not p.get('featured'):
            row.append(InlineKeyboardButton("⭐ Öne Çıkar", callback_data=f"feat_{p['id']}"))
        keyboard.append(row)
    return '\n'.join(lines), InlineKeyboardMarkup(keyboard)


async def cmd_liste(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return
    try:
        posts, _ = get_posts()
        if not posts:
            await update.message.reply_text("Henüz yazı yok.")
            return
        text, markup = liste_message(posts)
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=markup)
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def cmd_sil(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return
    if not context.args:
        await update.message.reply_text("Kullanım: /sil <yazı-id>")
        return
    post_id = context.args[0]
    try:
        posts, sha = get_posts()
        before = len(posts)
        removed = [p for p in posts if p['id'] == post_id]
        posts = [p for p in posts if p['id'] != post_id]
        if len(posts) == before:
            await update.message.reply_text(f"❌ '{post_id}' bulunamadı.")
            return
        if removed:
            try: move_to_trash(removed)
            except Exception: pass
        if posts:
            for p in posts:
                p['featured'] = False
            posts[0]['featured'] = True
        save_posts(posts, sha, f"Silindi: {post_id}")
        await update.message.reply_text(f"🗑️ '{post_id}' çöp kutusuna taşındı (admin panelinden geri yüklenebilir).")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def cmd_duzenle(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return
    if not context.args:
        await update.message.reply_text("Kullanım: /duzenle <yazı-id>")
        return
    post_id = context.args[0]
    try:
        posts, _ = get_posts()
        post = next((p for p in posts if p['id'] == post_id), None)
        if not post:
            await update.message.reply_text(f"❌ '{post_id}' bulunamadı.")
            return
        pending_edit[update.effective_user.id] = post_id
        await update.message.reply_text(
            f"✏️ *{post['title']}* düzenleniyor\\.\n\n"
            f"Yeni içeriği gönder:\n"
            f"`Başlık: ...`\n`Kategori: ...`\n`Özet: ...`\n\nİçerik\\.\\.\\.\n\n"
            f"İptal için /iptal",
            parse_mode='MarkdownV2'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def cmd_onecikart(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return
    if not context.args:
        await update.message.reply_text("Kullanım: /onecikart <yazı-id>")
        return
    post_id = context.args[0]
    try:
        posts, sha = get_posts()
        found = False
        for p in posts:
            if p['id'] == post_id:
                p['featured'] = True
                found = True
            else:
                p['featured'] = False
        if not found:
            await update.message.reply_text(f"❌ '{post_id}' bulunamadı.")
            return
        posts.insert(0, posts.pop(next(i for i, p in enumerate(posts) if p['id'] == post_id)))
        save_posts(posts, sha, f"Öne çıkarıldı: {post_id}")
        await update.message.reply_text(f"⭐ '{post_id}' öne çıkarıldı.")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def cmd_migrate(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return
    try:
        posts, sha = get_posts()
        for i, p in enumerate(posts, 1):
            p['id'] = str(i)
        save_posts(posts, sha, "Yazı ID'leri 1-2-3 formatına güncellendi")
        lines = [f"✅ *{len(posts)} yazı güncellendi\\!*\n"]
        for p in posts:
            star = "⭐ " if p.get('featured') else ""
            lines.append(f"{star}*{p['id']}* — {p['title']}")
        lines.append("\nArtık `/sil 1`, `/duzenle 2` gibi kullanabilirsin\\.")
        await update.message.reply_text('\n'.join(lines), parse_mode='MarkdownV2')
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def cmd_iptal(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return
    pending_edit.pop(update.effective_user.id, None)
    pending.pop(update.effective_user.id, None)
    await update.message.reply_text("❌ İptal edildi.")


# ── Mesaj işleme ────────────────────────────────────────────────────────────

async def handle_message(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return

    uid = update.effective_user.id
    text = update.message.text

    # Düzenleme modu
    if uid in pending_edit:
        post_id = pending_edit.pop(uid)
        new_post = parse_structured(text) or parse_auto(text)
        if not new_post or not new_post.get('title'):
            await update.message.reply_text("❌ Yazı çok kısa.")
            return
        try:
            posts, sha = get_posts()
            idx = next((i for i, p in enumerate(posts) if p['id'] == post_id), None)
            if idx is None:
                await update.message.reply_text(f"❌ '{post_id}' artık bulunamadı.")
                return
            new_post['id'] = post_id
            new_post['featured'] = posts[idx].get('featured', False)
            posts[idx] = new_post
            save_posts(posts, sha, f"Güncellendi: {post_id}")
            await update.message.reply_text(f"✅ *{new_post['title']}* güncellendi.", parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"❌ Hata: {e}")
        return

    post = parse_structured(text) or parse_auto(text)

    if not post or not post.get('title'):
        await update.message.reply_text("❌ Yazı çok kısa. Lütfen daha uzun bir metin gönder.")
        return

    pending[update.effective_user.id] = post

    preview = (
        f"📝 *Şu şekilde yayınlayayım mı?*\n\n"
        f"📌 *Başlık:* {post['title']}\n"
        f"🏷️ *Kategori:* {post['category']}\n"
        f"⏱️ *Okuma süresi:* {post['readTime']}\n"
        f"📅 *Tarih:* {post['date']}\n\n"
        f"📋 *Özet:*\n{post['excerpt']}"
    )
    await update.message.reply_text(preview, parse_mode='Markdown', reply_markup=confirm_keyboard())


async def handle_callback(update: Update, context):
    query = update.callback_query
    await query.answer()

    if query.from_user.id not in ALLOWED_IDS:
        return

    uid = query.from_user.id

    if query.data == "cancel":
        pending.pop(uid, None)
        await query.edit_message_text("❌ İptal edildi.")
        return

    if query.data == "edit":
        pending.pop(uid, None)
        await query.edit_message_text(
            "✏️ Düzenlenmiş metni gönder.\n\n"
            "İstersen şu formatı kullan:\n"
            "Başlık: ...\nKategori: ...\nÖzet: ...\n\nİçerik..."
        )
        return

    if query.data.startswith("del_"):
        post_id = query.data[4:]
        try:
            posts, sha = get_posts()
            deleted = next((p for p in posts if p['id'] == post_id), None)
            if not deleted:
                await query.answer("Bu yazı zaten silinmiş.", show_alert=True)
                return
            try: move_to_trash([deleted])
            except Exception: pass
            posts = [p for p in posts if p['id'] != post_id]
            if posts:
                for p in posts:
                    p['featured'] = False
                posts[0]['featured'] = True
            save_posts(posts, sha, f"Silindi: {deleted['title']}")
            if posts:
                text, markup = liste_message(posts)
                await query.edit_message_text(
                    f"✅ *{deleted['title']}* silindi.\n\n" + text,
                    parse_mode='Markdown', reply_markup=markup
                )
            else:
                await query.edit_message_text("✅ Silindi. Artık yazı yok.")
        except Exception as e:
            await query.edit_message_text(f"❌ Hata: {e}")
        return

    if query.data.startswith("feat_"):
        post_id = query.data[5:]
        try:
            posts, sha = get_posts()
            featured = next((p for p in posts if p['id'] == post_id), None)
            if not featured:
                await query.answer("Yazı bulunamadı.", show_alert=True)
                return
            for p in posts:
                p['featured'] = p['id'] == post_id
            idx = next(i for i, p in enumerate(posts) if p['id'] == post_id)
            posts.insert(0, posts.pop(idx))
            save_posts(posts, sha, f"Öne çıkarıldı: {featured['title']}")
            text, markup = liste_message(posts)
            await query.edit_message_text(
                f"⭐ *{featured['title']}* öne çıkarıldı.\n\n" + text,
                parse_mode='Markdown', reply_markup=markup
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Hata: {e}")
        return

    post = pending.pop(uid, None)
    if not post:
        await query.edit_message_text("❌ Bekleyen yazı bulunamadı.")
        return

    try:
        posts, sha = get_posts()
        for p in posts:
            p['featured'] = False
        post['featured'] = True
        posts.insert(0, post)
        save_posts(posts, sha, post['title'])
        page_url = f"https://yargikalemi.com/posts/{post.get('slug', make_slug(post['title']))}.html"
        page_err = None
        try:
            save_post_page(post)
        except Exception as pe:
            logging.warning(f"Sayfa oluşturulamadı: {pe}")
            page_url = None
            page_err = str(pe)
        page_note = f"\n🔗 {page_url}" if page_url else f"\n⚠️ Sayfa oluşturulamadı: {page_err}"
        await query.edit_message_text(
            f"✅ *Yayınlandı!*\n\n"
            f"📌 {post['title']}\n"
            f"🏷️ {post['category']} · {post['date']} · {post['readTime']}"
            f"{page_note}\n\n"
            f"Site 1-2 dakika içinde güncellenecek.",
            parse_mode='Markdown'
        )
    except Exception as e:
        await query.edit_message_text(f"❌ Hata: {e}")


# ── Başlat ──────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("liste", cmd_liste))
    app.add_handler(CommandHandler("sil", cmd_sil))
    app.add_handler(CommandHandler("duzenle", cmd_duzenle))
    app.add_handler(CommandHandler("onecikart", cmd_onecikart))
    app.add_handler(CommandHandler("migrate", cmd_migrate))
    app.add_handler(CommandHandler("iptal", cmd_iptal))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info(f"Bot başlatıldı. ALLOWED_IDS={ALLOWED_IDS}, REPO={REPO}, TOKEN_START={GITHUB_TOKEN[:8] if GITHUB_TOKEN else 'YOK'}")
    app.run_polling()


if __name__ == '__main__':
    main()
