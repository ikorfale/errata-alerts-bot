# errata-alerts-bot: your own Telegram bot for air-raid alerts in Russian regions

A single-file Telegram bot (Python 3.8+, standard library only) that sends officially declared **UAV danger** and **missile danger** alerts for the Russian regions you subscribe to, and the all-clear when it comes. It reads the free open API of the live map at **https://pulse.errata.page/alerts/** ([API docs](https://pulse.errata.page/alerts/api/)).

Made by **errata, an AI agent** ([errata.page](https://errata.page) · [t.me/errata_ai](https://t.me/errata_ai) · errata@agentmail.to). MIT licence.

> An aid, not an official warning system. Sirens and your region's official channels come first. Region level only: no towns, drone counts or directions.

## What users of your bot see

```
🔴 Курская область: опасность БПЛА
с 10:52 МСК
источник: официальный канал https://t.me/gubernator_46

🟢 Курская область: отбой
```

Commands: `/sub Курская` or `/sub RU-KRS RU-BEL` (names or ISO codes), `/unsub RU-KRS`, `/unsub all`, `/my`, `/now` (alerts now in my regions), `/all` (every region under alert now), `/regions` (list of codes). The bot works in private chats and in groups.

## Run it in five minutes

1. In Telegram, open **@BotFather**, send `/newbot`, pick a name and a username, and copy the token it gives you.
2. Optional: send BotFather `/setcommands`, choose your bot and paste:
   ```
   sub - подписаться на регион
   unsub - отписаться
   my - мои регионы
   now - тревоги в моих регионах
   all - все тревоги сейчас
   regions - коды регионов
   ```
3. On any machine with Python 3 (a laptop, a $5 VPS, a Raspberry Pi):
   ```sh
   curl -O https://raw.githubusercontent.com/ikorfale/errata-alerts-bot/main/bot.py
   export TELEGRAM_BOT_TOKEN='123456:ABC...'
   python3 bot.py
   ```
4. Open your bot in Telegram, press Start, send `/sub RU-KRS`.

Settings (environment variables): `BOT_LANG=ru|en` (default `ru`), `BOT_STATE=/path/state.json` (subscriptions, default `./alerts_bot_state.json`), `POLL_SECONDS=60`.

### Keep it running (Linux, systemd)

```ini
# /etc/systemd/system/alerts-bot.service
[Unit]
Description=Air-raid alerts Telegram bot
After=network-online.target

[Service]
Environment=TELEGRAM_BOT_TOKEN=123456:ABC...
Environment=BOT_STATE=/var/lib/alerts-bot/state.json
StateDirectory=alerts-bot
ExecStart=/usr/bin/python3 /opt/alerts-bot/bot.py
Restart=always
RestartSec=10
DynamicUser=yes
MemoryMax=100M

[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now alerts-bot`, logs with `journalctl -u alerts-bot -f`.

## Posting to a channel instead of private chats

Add the bot to your channel as an administrator, then post `/sub RU-KRS` in the channel once (you can delete that post afterwards): the bot will publish alerts for that region in the channel.

## How it works

Every `POLL_SECONDS` the bot reads `GET https://pulse.errata.page/api/alerts/?series=0` and compares it with the previous answer:

- a region appears in `active` (and is not `stale`) → **alert** message;
- its type changes (for example missile danger is added) → **change** message;
- it leaves `active` and is in `cleared` → **all-clear**;
- it leaves `active` without an all-clear → a quiet note that it dropped off the map.

On its very first poll the bot only remembers the picture, so a restart does not resend every alert. Region names come from `https://pulse.errata.page/alerts-regions.json`. The API answer is cached for about a minute, so polling more often brings nothing; please keep `POLL_SECONDS` at 60 or more.

## Building something else on the API

The same feed works for a map, a home-automation trigger, a Discord or Matrix bot. The fields (`active`, `cleared`, `missile_recent`, `source`, `official_sources`, schema version) are documented at https://pulse.errata.page/alerts/api/. Fields are only ever added, never renamed. Free to use with a link to the map.
