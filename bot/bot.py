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
ALLOWED_IDS = {7284939267, 8092559336} | set(
    int(x.strip()) for x in os.getenv('ALLOWED_USER_ID', '').split(',') if x.strip().isdigit()
)

MONTHS = ['', 'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
          'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']

CATEGORY_KEYWORDS = {
    'Ceza Hukuku':  ['gözaltı', 'tutuklama', 'suç', 'hapis', 'ceza', 'sanık', 'beraat',
                     'savcı', 'kovuşturma', 'soruşturma', 'adli', 'cezai', 'iddianame',
                     'susma', 'ifade', 'zamanaşımı', 'mahkeme', 'duruşma'],
    'Mali Hukuk':   ['tazminat', 'işçi', 'işveren', 'ücret', 'vergi', 'borç', 'alacak',
                     'sözleşme', 'kira', 'icra', 'iflas', 'kıdem', 'ihbar', 'fesih',
                     'adli yardım', 'baro', 'harç'],
    'Aile Hukuku':  ['boşanma', 'nafaka', 'velayet', 'evlilik', 'çocuk', 'miras',
                     'aile', 'eş', 'nişan', 'evlat', 'mal paylaşımı'],
    'İdare Hukuku': ['idare', 'devlet', 'belediye', 'kamu', 'ihale', 'disiplin',
                     'memur', 'yönetim', 'bakanlık', 'kurum', 'iptal', 'danıştay'],
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
    "*Kategoriler:* Ceza Hukuku · Mali Hukuk · Aile Hukuku · İdare Hukuku\n\n"
    "*Komutlar:*\n"
    "/liste — yayındaki yazılar (ID numaralarıyla)\n"
    "/sil 3 — 3 numaralı yazıyı sil\n"
    "/duzenle 3 — 3 numaralı yazıyı güncelle\n"
    "/onecikart 3 — 3 numaralı yazıyı öne çıkar\n"
    "/istatistik — yazı sayısı ve kategoriler\n"
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
    url = f"https://api.github.com/repos/{REPO}/contents/posts.json"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    res = requests.get(url, headers=headers, timeout=15)
    if res.status_code != 200:
        raise Exception(f"GitHub okuma hatası: {res.status_code}")
    data = res.json()
    content = base64.b64decode(data['content']).decode('utf-8')
    return json.loads(content), data['sha']


def save_posts(posts, sha, title):
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
    return re.sub(r'[^a-z0-9]+', '-', slug)[:50].strip('-')


def build_post(title, category, excerpt, content_raw):
    now = datetime.now()
    return {
        "id": make_slug(title),
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


async def cmd_liste(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return
    try:
        posts, _ = get_posts()
        if not posts:
            await update.message.reply_text("Henüz yazı yok.")
            return
        lines = [f"📋 *Yayındaki Yazılar ({len(posts)})*\n"]
        for p in posts:
            star = "⭐ " if p.get('featured') else ""
            lines.append(f"{star}*{p['id']}* — {p['title']}")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
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
        posts = [p for p in posts if p['id'] != post_id]
        if len(posts) == before:
            await update.message.reply_text(f"❌ '{post_id}' bulunamadı.")
            return
        if posts:
            for p in posts:
                p['featured'] = False
            posts[0]['featured'] = True
        save_posts(posts, sha, f"Silindi: {post_id}")
        await update.message.reply_text(f"✅ '{post_id}' silindi.")
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


async def cmd_istatistik(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return
    try:
        posts, _ = get_posts()
        if not posts:
            await update.message.reply_text("Henüz yazı yok.")
            return
        cat_counts = {}
        for p in posts:
            cat = p.get('category', 'Diğer')
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
        lines = [f"📊 *İstatistikler*\n", f"📝 Toplam yazı: {len(posts)}\n"]
        for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  • {cat}: {count}")
        featured = next((p for p in posts if p.get('featured')), None)
        if featured:
            lines.append(f"\n⭐ Öne çıkan: {featured['title']}")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
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

    post = pending.pop(uid, None)
    if not post:
        await query.edit_message_text("❌ Bekleyen yazı bulunamadı.")
        return

    try:
        posts, sha = get_posts()
        nums = [int(p['id']) for p in posts if str(p['id']).isdigit()]
        post['id'] = str(max(nums, default=0) + 1)
        for p in posts:
            p['featured'] = False
        post['featured'] = True
        posts.insert(0, post)
        save_posts(posts, sha, post['title'])
        await query.edit_message_text(
            f"✅ *Yayınlandı!*\n\n"
            f"📌 {post['title']}\n"
            f"🏷️ {post['category']} · {post['date']} · {post['readTime']}\n\n"
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
    app.add_handler(CommandHandler("istatistik", cmd_istatistik))
    app.add_handler(CommandHandler("migrate", cmd_migrate))
    app.add_handler(CommandHandler("iptal", cmd_iptal))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info(f"Bot başlatıldı. ALLOWED_IDS={ALLOWED_IDS}, REPO={REPO}, TOKEN_START={GITHUB_TOKEN[:8] if GITHUB_TOKEN else 'YOK'}")
    app.run_polling()


if __name__ == '__main__':
    main()
