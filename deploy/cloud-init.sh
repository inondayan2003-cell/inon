#!/bin/bash
# מדביקים את זה ב-Oracle בזמן יצירת שרת חדש: Advanced options → Management → Initialization script → Paste
# השרת יתקין ויפעיל את הבוט לבד, בלי צורך להתחבר אליו. מחליפים רק את שתי השורות הבאות:
export BOT_TOKEN="PASTE_BOT_TOKEN_HERE"
export TWELVEDATA_API_KEY="PASTE_TWELVEDATA_KEY_HERE"
curl -fsSL https://raw.githubusercontent.com/inondayan2003-cell/inon/claude/telegram-stocks-gold-analyzer-akepc8/deploy/install.sh | bash > /var/log/gold-install.log 2>&1
