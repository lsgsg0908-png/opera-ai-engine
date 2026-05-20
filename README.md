# OPERA AI — Local AI Operating Environment

A local-first AI operating environment for Windows and Mac.

## Quick Start (Desktop App)

```bash
cd opera_desktop
npm install
npm start
```

## Build Installer

```bash
# Windows
npm run build:win
# Output: dist/OPERA AI Setup.exe

# macOS
npm run build:mac
# Output: dist/OPERA AI.dmg
```

## Architecture

```
opera_desktop/          — Electron Desktop App
opera_engine/           — Python AI Engine (server-side)
main.py                 — API server (FastAPI)
```

## Requirements

- Node.js 18+
- Python 3.10+
- npm or yarn

## Links

- Website: https://opera-ai.net
- Waitlist: https://admin.opera-ai.net/waitlist-admin
- API: https://api.opera-ai.net

## License

Private alpha — not for redistribution.
