import os
import json
import base64
import re
import logging
from datetime import datetime
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = os.getenv('TELEGRAM_TOKEN', '')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN', '')
REPO = os.getenv('GITHUB_REPO', 'erdemkapkara/Kurt')
ALLOWED_IDS = {7284939267, 8092559336} | set(
    int(x.strip()) for x in os.getenv('ALLOWED_USER_ID', '').split(',') if x.strip().isdigit()
)

MONTHS = ['', 'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
          'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']

HELP_TEXT = (
    "👨‍⚖️ *KURT Blog Botu*\n\n"
    "Yeni yazı eklemek için şu formatı kullan:\n\n"
    "```\n"
    "Başlık: Yazı başlığı buraya\n"
    "Kategori: Ceza Hukuku\n"
    "Özet: Okuyucuyu çeken kısa açıklama.\n\n"
    "Yazı içeriği buraya gelecek.\n\n"
    "Her boş satır yeni paragraf demek.\n"
    "```\n\n"
    "*Kategoriler:*\n"
    "• Ceza Hukuku\n"
    "• Mali Hukuk\n"
    "• Aile Hukuku\n"
    "• İdare Hukuku\n\n"
    "Yeni yazı otomatik olarak öne çıkan yazı olur ve site 1-2 dakikada güncellenir."
)


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
    payload = {"message": f"Yeni yazı: {title}", "content": encoded, "sha": sha}
    res = requests.put(url, headers=headers, json=payload, timeout=15)
    if res.status_code not in (200, 201):
        raise Exception(f"GitHub yazma hatası: {res.status_code}")


def parse_post(text):
    title_m = re.search(r'Başlık:\s*(.+)', text)
    cat_m = re.search(r'Kategori:\s*(.+)', text)
    excerpt_m = re.search(r'Özet:\s*(.+)', text)

    if not (title_m and cat_m and excerpt_m):
        return None

    # İçerik: son header'dan sonraki ilk boş satırdan itibaren
    headers_end = max(title_m.end(), cat_m.end(), excerpt_m.end())
    raw_content = text[headers_end:].strip()

    # Paragrafları HTML'e çevir
    paragraphs = [p.strip() for p in raw_content.split('\n\n') if p.strip()]
    content_html = ''.join(
        f'<p>{p.replace(chr(10), " ")}</p>' for p in paragraphs
    ) if paragraphs else f'<p>{excerpt_m.group(1).strip()}</p>'

    # Slug oluştur
    slug = re.sub(r'[^a-z0-9]+', '-', title_m.group(1).lower().strip()[:50]).strip('-')

    # Okuma süresi tahmini (200 kelime/dk)
    word_count = len(raw_content.split())
    read_time = max(1, round(word_count / 200))

    now = datetime.now()
    return {
        "id": slug,
        "featured": False,
        "title": title_m.group(1).strip(),
        "category": cat_m.group(1).strip(),
        "excerpt": excerpt_m.group(1).strip(),
        "date": f"{now.day} {MONTHS[now.month]} {now.year}",
        "readTime": f"{read_time} dk",
        "content": content_html
    }


async def cmd_start(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return
    await update.message.reply_text(HELP_TEXT, parse_mode='Markdown')


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
            await update.message.reply_text(f"❌ '{post_id}' ID'li yazı bulunamadı.")
            return
        # İlk yazıyı featured yap
        if posts:
            for p in posts:
                p['featured'] = False
            posts[0]['featured'] = True
        save_posts(posts, sha, f"Silindi: {post_id}")
        await update.message.reply_text(f"✅ '{post_id}' silindi. Site 1-2 dakikada güncellenir.")
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


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
            lines.append(f"{star}`{p['id']}`\n  {p['title']}\n")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Hata: {e}")


async def handle_message(update: Update, context):
    if update.effective_user.id not in ALLOWED_IDS:
        return

    text = update.message.text
    post = parse_post(text)

    if not post:
        await update.message.reply_text(
            "❌ Format hatalı. Başlık, Kategori ve Özet alanları zorunlu.\n\n"
            "/start yazarak formatı görebilirsin."
        )
        return

    try:
        posts, sha = get_posts()

        # Mevcut yazıların featured durumunu kaldır
        for p in posts:
            p['featured'] = False

        # Yeni yazı en başa, öne çıkan olarak ekle
        post['featured'] = True
        posts.insert(0, post)

        save_posts(posts, sha, post['title'])

        await update.message.reply_text(
            f"✅ *Yazı yayınlandı!*\n\n"
            f"📌 {post['title']}\n"
            f"🏷️ {post['category']}\n"
            f"📅 {post['date']} · {post['readTime']}\n\n"
            f"Site 1-2 dakika içinde güncellenecek.",
            parse_mode='Markdown'
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Hata oluştu:\n{e}")


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("sil", cmd_sil))
    app.add_handler(CommandHandler("liste", cmd_liste))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logging.info(f"Bot başlatıldı. ALLOWED_IDS={ALLOWED_IDS}")
    app.run_polling()


if __name__ == '__main__':
    main()
