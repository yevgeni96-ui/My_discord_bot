# Discord Bot

A Discord bot for vibros time calculation and role self-assignment via buttons.

## Setup

1. Create a Python virtual environment:

```powershell
python -m venv .venv
```

2. Activate it and install requirements:

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and fill in your values:

```powershell
copy .env.example .env
```

4. Run the bot:

```powershell
.venv\Scripts\python.exe bot.py
```

## Commands

- `!vibros` or aliases `!vib`, `!v`, `!emmision`
- `!roles`
- `!reloadroles`

## Notes

- The bot reads `DISCORD_TOKEN`, `PING_ROLE_ID`, and `GUILD_ID` from `.env`.
- Do not commit `.env` to GitHub.
