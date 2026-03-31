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
🎮 *GearCheck Bot v3*

Second-hand tech & gaming gear price analyzer for Turkey.

*How to use:*
Type product name + price. Color/variant optional.

*Examples:*
• `PS5 controller 3500`
• `iPhone 14 Pro Max black 28000`
• `RTX 3060 8000`
• `MacBook Air M1 space gray 25000`
• `Xbox Elite Core 2 white 6100`

Price in TL. That's it!
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
            "Didn't get that 🤔\n\nFormat: `Product name PRICE`\n\nExample: `PS5 controller 3500`",
            parse_mode='Markdown'
        )
        return

    thinking_msg = await update.message.reply_text("🔍 Researching...")

    prompt = f"""You are a Turkish second-hand tech and gaming gear market expert helping a reseller decide whether to buy an item for resale profit.

Item: "{item}" listed for {price} TL.

IMPORTANT: Write ALL text fields in clear, natural English only. No Turkish, no mixed language.

Search the web for:
1. Current Turkish market prices (Sahibinden, Letgo, Akakce, Cimri, Trendyol, Hepsiburada, Vatan, MediaMarkt TR)
2. Demand and how fast this sells in Turkey
3. If a color or variant is mentioned, compare its popularity vs other colors/variants in Turkey

Respond ONLY with a raw JSON object, no markdown, no backticks, no extra text:
{{
  "itemName": "clean product name including color/variant if specified",
  "listingPrice": {price},
  "avgUsedPrice": <average second-hand price in TL as integer>,
  "retailPrice": <new retail price in TL as integer>,
  "recommendedResellPrice": <what it should sell for used in TL as integer>,
  "verdict": "BUY" or "SKIP" or "MAYBE",
  "discountPercent": <how far below market as integer, negative if overpriced>,
  "estimatedProfit": <expected profit in TL as integer>,
  "marginPercent": <profit margin 0-100 as integer>,
  "demandScore": <integer 0-100 representing demand in Turkish secondhand market>,
  "demandLabel": "Very hard to sell" or "Moderate demand" or "Good demand" or "Sells very fast",
  "avgDaysToSell": <estimated days to sell as integer>,
  "colorInsight": "If color or variant was specified: one sentence on how this color/variant compares to others in Turkish market. If not specified: empty string",
  "reasoning": "2-3 clear sentences in English explaining the deal quality and whether it is worth buying for resale",
  "warnings": ["specific red flags in English, empty array if none"],
  "tip": "one practical, specific reselling tip in English for this exact item"
}}

Demand score guide:
0-25: Very hard to sell (niche, low demand, sits for weeks)
26-50: Moderate demand (sells in 1-2 weeks)
51-75: Good demand (sells within a few days)
76-100: Sells very fast (same day or next day)"""

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
            raise ValueError("Could not parse response.")
        r = json.loads(m.group(0))

        verdict_emoji = {"BUY": "✅", "SKIP": "❌", "MAYBE": "🤔"}.get(r["verdict"], "🤔")
        verdict_text = {"BUY": "BUY", "SKIP": "SKIP", "MAYBE": "THINK"}.get(r["verdict"], "THINK")

        discount = r["discountPercent"]
        if discount > 0:
            discount_line = f"📉 *{abs(discount)}% below* market average"
        elif discount < 0:
            discount_line = f"📈 *{abs(discount)}% above* market average"
        else:
            discount_line = "➡️ At market price"

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

        color_text = ""
        if r.get("colorInsight"):
            color_text = f"\n\n🎨 *Color/Variant:* {r['colorInsight']}"

        warnings_text = ""
        if r.get("warnings"):
            warnings_text = "\n\n⚠️ *Watch out:*\n" + "\n".join(f"• {w}" for w in r["warnings"])

        tip_text = f"\n\n💡 *Tip:* {r['tip']}" if r.get("tip") else ""

        reply = f"""{verdict_emoji} *{r['itemName']}* — {verdict_text}

📊 *Price Analysis*
• Listed: *{int(r['listingPrice']):,} TL*
• Used avg: *{int(r['avgUsedPrice']):,} TL*
• Retail new: ~{int(r['retailPrice']):,} TL
• Recommended resell: ~{int(r['recommendedResellPrice']):,} TL

{discount_line}
{profit_emoji} Est. profit: *{profit_sign}{int(profit):,} TL* ({r['marginPercent']}% margin)

{demand_emoji} *Demand Score: {score}/100*
`{demand_bar}`
_{demand_label}_
⏱ Est. days to sell: *~{days} days*

📝 {r['reasoning']}{color_text}{warnings_text}{tip_text}"""

        await thinking_msg.edit_text(reply.replace(',', '.'), parse_mode='Markdown')

    except Exception as e:
        await thinking_msg.edit_text(f"❌ Error: {str(e)}\n\nPlease try again.")

def main():
    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_TOKEN not set!")
        return
    if not ANTHROPIC_API_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set!")
        return

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, analyze))

    print("✅ GearCheck bot v3 running...")
    app.run_polling()

if __name__ == "__main__":
    main()
