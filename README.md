<div align="center">

<img width="100%" alt="header" src="https://capsule-render.vercel.app/api?type=waving&height=210&text=ThunderWaves%20Bot&fontAlign=50&fontAlignY=36&fontSize=56&desc=Auto%20Tasks%20%7C%20Reward%20Ads%20%7C%20Thirteen%20Games%20%7C%20Daily%20Streak%20%7C%20Multi-Account&descAlign=50&descAlignY=58"/>

<img alt="typing" src="https://readme-typing-svg.demolab.com?font=Inter&size=18&duration=3000&pause=650&center=true&vCenter=true&width=900&lines=Auto+Complete+Tasks+%7C+Claim+Every+Available+Reward;Auto+Reward+Ads+%7C+Watch+And+Settle+Each+Slot;Auto+Games+%7C+Thirteen+Titles+Played+To+The+Reward+Cap;Auto+Streak+Check+%7C+Daily+Bonus+Verification;Proxy+Support+%7C+Multi-Account"/>

<p>
  <img alt="python" src="https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white"/>
  <img alt="platform" src="https://img.shields.io/badge/Platform-ThunderWaves%20Miniapp-111111"/>
  <img alt="multi-account" src="https://img.shields.io/badge/Multi--Account-Supported-111111"/>
  <img alt="proxy" src="https://img.shields.io/badge/Proxy-Supported-111111"/>
  <img alt="author" src="https://img.shields.io/badge/by-Yuurisandesu-111111"/>
</p>

<p>
  <b>ThunderWaves Bot</b> is a full automation bot for the ThunderWaves Telegram Miniapp.<br/>
  It handles the complete daily cycle: social and partner tasks, reward advertisements, thirteen arcade games, the daily streak check, and the account summary, all running automatically across multiple accounts with proxy support and a live countdown between cycles.<br/>
  Built and distributed by <b>Yuurisandesu</b>.
</p>

</div>

---

## Table of Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Bot](#running-the-bot)
- [Features](#features)
- [File Structure](#file-structure)
- [Disclaimer](#disclaimer)

---

## Requirements

- Python `3.12+`
- Git

---

## Installation

**Clone the repository:**

```bash
git clone https://github.com/Yuurisan-N1/Thunderwaves-Miniapp.git
cd Thunderwaves-Miniapp
```

**Install dependencies:**

```bash
pip install aiohttp yuurisan
```

---

## Configuration

### 1. Accounts (data.txt)

Fill `data.txt` with Telegram WebApp `initData` for each account, one per line:

```
user=%7B%22id%22...&hash=abc123
user=%7B%22id%22...&hash=def456
```

> `initData` can be obtained from the browser DevTools when opening ThunderWaves on Telegram Web.

### 2. Proxy (proxy.txt)

Fill `proxy.txt` with proxies, one per line (optional, leave empty to run without proxy):

```
host:port
host:port:user:pass
http://user:pass@host:port
```

Proxies are assigned to accounts by index in round-robin order.

### 3. Bot Settings (config.json)

`sleep_seconds` controls how many seconds the bot waits between cycles. If `config.json` is missing, it is created automatically with a default of `3600` seconds.

---

## Running the Bot

```bash
python bot.py
```

Press `Ctrl+C` at any time to stop the bot cleanly.

---

## Features

### Daily Streak

The bot reads the streak panel and settles the daily bonus whenever the server still allows it. A streak that is already collected is reported once and never retried, and a streak that still needs the invite link in the Telegram bio is reported instead of being forced.

### Tasks

Every task category is walked in server order. Advertisement tasks are watched slot by slot until the server reports the task complete, and link tasks send a start request, wait the task timer, then settle the task. Tasks that need a real channel join, or that already reached their daily limit, are reported once and skipped.

### Reward Advertisements

Each advertisement is started on the server, held for the watch duration the server demands, and only then settled, so the credited amount always comes from a server response. The credited reward is read back from the server counter before it is logged.

### Games

Thirteen titles are played to the reward cap of the chosen difficulty: the lucky spin, 2048, the stack tower, snake, the basketball round, the endless racer, the space shooter, wordle, the word search, the word scramble, the memory grid, quick maths, and tic tac toe. Every round is replayed through the server verifier, and the reward of each finished round is collected through the game reward advertisement before the next round starts. Rounds that the server already used up today are skipped silently.

### Multi Account

All accounts in `data.txt` are processed sequentially within every cycle. The bot logs the sign in line, every credited action, and the account totals for each account. The cycle number is tracked and logged at the start of each round.

### Proxy Support

Proxies are loaded from `proxy.txt` and assigned to accounts by position in round-robin order. Proxy credentials are masked in log output. Running without proxies is fully supported.

### Auto Countdown

After all accounts complete a cycle, the bot displays a live `HH:MM:SS` countdown until the next cycle starts.

---

## File Structure

```text
ThunderWaves-Miniapp/
├── bot.py          # Main bot, full daily cycle automation
├── config.json     # Sleep duration between cycles
├── data.txt        # Account initData, one per line
├── proxy.txt       # Proxy list, one per line (optional)
├── LICENSE         # License file
└── utils/
    └── banner.py   # Banner using yuurisan module
```

---

## Disclaimer

This tool is built for educational and technical exploration purposes. Use it wisely and at your own responsibility.

---

<div align="center">
<img width="100%" alt="footer" src="https://capsule-render.vercel.app/api?type=waving&height=120&section=footer"/>
</div>