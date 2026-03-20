# Cron-Job Fix-Anweisungen

## Fix 1: Selektives Löschen statt `crontab -r`

**Alt (AUFGAE 6):**
```bash
crontab -r
```

**Neu:**
```bash
crontab -l | grep -v "trading" | crontab -
```

## Fix 2: Schritt 10 ohne `| sort -u`

**Alt:**
```bash
(crontab -l 2>/dev/null; echo "..."; echo "...") | sort -u | crontab -
```

**Neu:**
```bash
(crontab -l 2>/dev/null; echo "0 12,15,18,21 * * 1-5 cd ~/trading && /usr/bin/python3 sentiment_analyzer.py >> ~/trading/logs/cron.log 2>&1"; echo "*/30 15-21 * * 1-5 cd ~/trading && /usr/bin/python3 trading_bot.py --dry >> ~/trading/logs/cron.log 2>&1") | crontab -
```

**Wichtig:** Entferne `| sort -u` da es Cron-Zeilen mit einstelligen Minuten-Werten alphabetisch sortiert und damit beschädigt.
