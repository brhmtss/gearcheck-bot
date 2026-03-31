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
🎮 *GearCheck Bot*

İkinci el gaming gear için fiyat analizi.

*Nasıl kullanılır:*
Ürün adı ve fiyatı yaz, analiz geliyor.

*Örnekler:*
• `PS5 controller 3500`
• `RTX 3060 8000`
• `Xbox Elite Core 2 6100`
• `Logitech G502 850`

Fiyatı TL olarak yaz. Hepsi bu!
"""

def parse_input(text: str):
    text = text.strip()
    # Try to find a number at the end
    match = re.search(r'^(.*?)\s+(\d[\d.,]*)\s*(?:tl|₺)?$', text, re.IGNORECASE)
    if match:
        item = match.group(1).strip()
        price_str = match.group(2).replace(',', '').replace('.', '')
        try:
            return item, float(price_str)
        except:
            pass
    # Try to find a number anywhere
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

    prompt = f"""You are a Turkish second-hand gaming gear market expert helping a reseller decide whether to buy an item.

Item: "{item}" listed for {price} TL.

Search the web for current Turkish market prices. Check Sahibinden listings, Turkish retailers (Vatan, MediaMarkt TR, Trendyol, İtopya, Hepsiburada), and price comparison sites like Akakce and Cimri.

Respond ONLY with a raw JSON object, no markdown, no backticks, no explanation:
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
  "reasoning": "2-3 sentences in Turkish explaining the deal quality",
  "warnings": ["specific red flags in Turkish, empty array if none"],
  "tip": "one practical reselling tip for this specific item in Turkish"
}}"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}]
        )

        raw = ""
        for block in response.content:
            if block.type == "text":
                raw += block.text

        match = re.search(r'\{[\s\S]*\}', raw)
        if not match:
            raise ValueError("JSON bulunamadı")

        r = json.loads(match.group(0))

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

📝 {r['reasoning']}{warnings_text}{tip_text}"""

        await thinking_msg.edit_text(reply.replace(',', '.'), parse_mode='Markdown')

    except Exception as e:
        await thinking_msg.edit_text(
            f"❌ Bir hata oluştu: {str(e)}\n\nTekrar dene."
        )

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

    print("✅ GearCheck bot çalışıyor...")
    app.run_polling()

if __name__ == "__main__":
    main()
