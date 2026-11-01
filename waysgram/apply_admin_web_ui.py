#!/usr/bin/env python3
"""Patch the admin web UI to reveal allowlisted test OTPs to the authenticated admin."""
from pathlib import Path

page = Path("WaysGram-Backend/static/admin.html")
if not page.is_file():
    raise SystemExit(f"Missing WaysGram admin page: {page}")

html = page.read_text(encoding="utf-8")
old_help = "Тестовый код выводится только в консоль Termux для номера из NEXUSGRAM_TEST_PHONES. В production коды отправляются по SMS через подключённого провайдера от имени WaysGram."
new_help = "Код показывается только после входа администратора и только для номера из NEXUSGRAM_TEST_PHONES. В production DEV_OTP должен быть выключен, а коды отправляются SMS-провайдером для пользователей WaysGram."
old_function = """async function requestTestCode(){try{const d=await api('/api/admin/dev-code','POST',{phone:$('testPhone').value});status(d.message)}catch(e){status(e.message)}}"""
new_function = """async function requestTestCode(){try{const d=await api('/api/admin/dev-code','POST',{phone:$('testPhone').value});if(typeof d.test_code==='string' && /^\\d{6}$/.test(d.test_code)){status('Тестовый код: '+d.test_code+' (действует '+Math.ceil((d.expires_in||300)/60)+' мин.)')}else{status(d.message||'Код создан.')}}catch(e){status(e.message)}}"""

if old_help in html:
    html = html.replace(old_help, new_help, 1)
elif new_help not in html:
    raise SystemExit("The test-code help text did not match the expected source")

if old_function in html:
    html = html.replace(old_function, new_function, 1)
elif new_function not in html:
    raise SystemExit("The requestTestCode function did not match the expected source")

page.write_text(html, encoding="utf-8")
print("WaysGram admin page now displays allowlisted test OTPs to the authenticated administrator")
