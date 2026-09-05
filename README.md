# Daytrade Helper (phone-only)

Trade journal + price alerts in your phone browser. **Not installed on your PC.**

## Permanent phone URL (Render free)

Deploy once to the cloud. Then on iPhone: open the link → Share → **Add to Home Screen**.

### What you do on your phone (about 5 minutes)

1. Create a free account at [render.com](https://render.com) (Apple/Google sign-in is fine)
2. Open **Account Settings → API Keys → Create API Key**
3. Paste that key back in this chat as `RENDER_API_KEY=...`
4. Optional for push alerts: Telegram bot token + chat id (same chat)

I will deploy from here and reply with your permanent `https://….onrender.com` link.

### Notes

- Free Render apps **sleep after ~15 minutes idle**; first open can take 30–60 seconds to wake
- SQLite data can reset if the free service is fully rebuilt — fine for personal use; ask if you want durable storage later
- Your personal PC never runs this app

## Local / temporary (agent only)

Used only inside the cloud agent for testing — not your PC.
