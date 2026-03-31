import os
import re
import json
import anthropic
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

HELP_TEXT = """
🎮 *GearCheck Bot v2*

İkinci el teknoloji ürünleri için fiyat ve talep analizi.

*Nasıl kullanılır:*
Ürün adı ve fiyatı yaz, analiz geliyor.

*Örnekler:*
• `PS5 controller 3500`
• `RTX 3060 8000`
• `iPhone 14 12000`
• `Xbox Elite Core 2 6100`
• `MacBook Air M1 25000`

Fiyatı TL olarak yaz. Hepsi bu!
"""

def parse_input(text: str):
    text = text.strip()
    match = re.search(r'^(.*?)\s+(\d[\d.,]*)\s*(?:tl|₺)?$', text, re.IGNORECASE)
    if match:
        item = match.group(1).strip()
        price_str = match.group(2).replace(',', '').replace('.', '')
        try:
            return item, float(price_str)
        except:
            pass
    match = re.search(r'(\d[\d.,]{2,})', text)
    if match:
        price_str = match.group(1).replace(',', '').replace('.', '')
        item = text.replace(match.group(1), '').strip(' -:')
        try:
            return item, float(price_str)
        except:
            pass
    return None, None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode='Markdown')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode='Markdown')

async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith('/'):
        return

    item, price = parse_input(text)
    if not item or not price or price <= 0:
        await update.message.reply_text(
            "Anlayamadım 🤔\n\nŞu formatta yaz:\n`Ürün adı FIYAT`\n\nÖrnek: `PS5 controller 3500`",
            parse_mode='Markdown'
        )
        return

    thinking_msg = await update.message.reply_text("🔍 Araştırılıyor...")

    prompt = f"""You are a Turkish second-hand tech and gaming gear market expert helping a reseller decide whether to buy an item.

Item: "{item}" listed for {price} TL.

Search the web for:
1. Current Turkish market prices (Sahibinden, Letgo, Akakce, Cimri, Trendyol, Hepsiburada, Vatan, MediaMarkt TR)
2. How in-demand this item is in Turkey right now — how fast it sells, how many active listings, how popular

Respond ONLY with a raw JSON object, no markdown, no backticks:
{{
  "itemName": "clean product name",
  "listingPrice": {price},
  "avgUsedPrice": <average second-hand price in TL as integer>,
  "retailPrice": <new retail price in TL as integer>,
  "recommendedResellPrice": <what it should sell for used in TL as integer>,
  "verdict": "BUY" or "SKIP" or "MAYBE",
  "discountPercent": <how far below market as integer, negative if overpriced>,
  "estimatedProfit": <expected profit in TL as integer>,
  "marginPercent": <profit margin 0-100 as integer>,
  "demandScore": <integer 0-100 representing demand in Turkish secondhand market>,
  "demandLabel": "Çok zor satılır" or "İdare eder" or "İyi talep var" or "Çok hızlı satılır",
  "avgDaysToSell": <estimated days to sell as integer>,
  "reasoning": "2-3 sentences in Turkish explaining the deal",
  "warnings": ["red flags in Turkish, empty array if none"],
  "tip": "one practical reselling tip in Turkish"
}}

Demand score guide:
0-25: Çok zor satılır (niche, low demand, sits for weeks)
26-50: İdare eder (moderate, sells in 1-2 weeks)
51-75: İyi talep var (good demand, sells in days)
76-100: Çok hızlı satılır (very high demand, sells same/next day)"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )

        raw = ""
        for block in response.content:
            if block.type == "text":
                raw += block.text

        m = re.search(r'\{[\s\S]*\}', raw)
        if not m:
            raise ValueError("JSON bulunamadı")
        r = json.loads(m.group(0))

        verdict_emoji = {"BUY": "✅", "SKIP": "❌", "MAYBE": "🤔"}.get(r["verdict"], "🤔")
        verdict_text = {"BUY": "AL", "SKIP": "ALMA", "MAYBE": "DÜŞÜN"}.get(r["verdict"], "DÜŞÜN")

        discount = r["discountPercent"]
        if discount > 0:
            discount_line = f"📉 Piyasanın *%{abs(discount)}* altında"
        elif discount < 0:
            discount_line = f"📈 Piyasanın *%{abs(discount)}* üstünde"
        else:
            discount_line = "➡️ Piyasa fiyatında"

        profit = r["estimatedProfit"]
        profit_sign = "+" if profit > 0 else ""
        profit_emoji = "💰" if profit > 0 else "💸"

        score = r.get("demandScore", 50)
        filled = round(score / 10)
        empty = 10 - filled
        demand_bar = "█" * filled + "░" * empty
        demand_label = r.get("demandLabel", "")
        days = r.get("avgDaysToSell", "?")

        if score >= 76:
            demand_emoji = "🔥"
        elif score >= 51:
            demand_emoji = "📈"
        elif score >= 26:
            demand_emoji = "😐"
        else:
            demand_emoji = "🐌"

        warnings_text = ""
        if r.get("warnings"):
            warnings_text = "\n\n⚠️ *Dikkat et:*\n" + "\n".join(f"• {w}" for w in r["warnings"])

        tip_text = f"\n\n💡 *İpucu:* {r['tip']}" if r.get("tip") else ""

        reply = f"""{verdict_emoji} *{r['itemName']}* — {verdict_text}

📊 *Fiyat Analizi*
• Listeleme: *{int(r['listingPrice']):,} TL*
• İkinci el ort: *{int(r['avgUsedPrice']):,} TL*
• Sıfır fiyatı: ~{int(r['retailPrice']):,} TL
• Tavsiye satış: ~{int(r['recommendedResellPrice']):,} TL

{discount_line}
{profit_emoji} Tahmini kâr: *{profit_sign}{int(profit):,} TL* (%{r['marginPercent']} marj)

{demand_emoji} *Talep Skoru: {score}/100*
`{demand_bar}`
_{demand_label}_
⏱ Tahmini satış süresi: *~{days} gün*

📝 {r['reasoning']}{warnings_text}{tip_text}"""

        await thinking_msg.edit_text(reply.replace(',', '.'), parse_mode='Markdown')

    except Exception as e:
        await thinking_msg.edit_text(f"❌ Bir hata oluştu: {str(e)}\n\nTekrar dene.")

def main():
    if not TELEGRAM_TOKEN:
        print("HATA: TELEGRAM_TOKEN ayarlanmamış!")
        return
    if not ANTHROPIC_API_KEY:
        print("HATA: ANTHROPIC_API_KEY ayarlanmamış!")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze))

    print("✅ GearCheck bot v2 çalışıyor...")
    app.run_polling()

if __name__ == "__main__":
    main()
