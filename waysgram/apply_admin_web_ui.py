#!/usr/bin/env python3
"""Patch the WaysGram admin web UI for test OTP and channel role management."""
from pathlib import Path

page = Path("WaysGram-Backend/static/admin.html")
if not page.is_file():
    raise SystemExit(f"Missing WaysGram admin page: {page}")

html = page.read_text(encoding="utf-8")

def replace_once(old: str, new: str, label: str) -> None:
    global html
    if old in html:
        html = html.replace(old, new, 1)
    elif new not in html:
        raise SystemExit(f"Could not patch admin UI section: {label}")

replace_once(
    "Тестовый код выводится только в консоль Termux для номера из NEXUSGRAM_TEST_PHONES. В production коды отправляются по SMS через подключённого провайдера от имени WaysGram.",
    "Код показывается только после входа администратора и только для номера из NEXUSGRAM_TEST_PHONES. В production DEV_OTP должен быть выключен, а коды отправляются SMS-провайдером для пользователей WaysGram.",
    "test-code help text",
)
replace_once(
    """async function requestTestCode(){try{const d=await api('/api/admin/dev-code','POST',{phone:$('testPhone').value});status(d.message)}catch(e){status(e.message)}}""",
    """async function requestTestCode(){try{const d=await api('/api/admin/dev-code','POST',{phone:$('testPhone').value});if(typeof d.test_code==='string' && /^\d{6}$/.test(d.test_code)){status('Тестовый код: '+d.test_code+' (действует '+Math.ceil((d.expires_in||300)/60)+' мин.)')}else{status(d.message||'Код создан.')}}catch(e){status(e.message)}}""",
    "test-code handler",
)

old_load = """async function loadChannels(){try{const d=await api('/api/admin/channels');$('channels').innerHTML=d.channels.map(c=>`<div class="item"><b>@${esc(c.username)}</b><div class="muted">${esc(c.title)} · ID ${c.id} · владелец @${esc(c.owner_username)} (ID ${c.owner_user_id})</div><div class="row"><input id="ct${c.id}" value="${esc(c.title)}" aria-label="Название"><input id="cu${c.id}" value="@${esc(c.username)}" aria-label="Username"><button onclick="editChannel(${c.id})">Сохранить</button><button class="danger" onclick="deleteChannel(${c.id})">Удалить</button></div></div>`).join('')||'<small>Каналов пока нет.</small>'}catch(e){status(e.message)}}"""
new_load = """async function loadChannels(){try{const d=await api('/api/admin/channels');$('channels').innerHTML=d.channels.map(c=>`<div class="item"><b>@${esc(c.username)}</b><div class="muted">${esc(c.title)} · ID ${c.id} · владелец @${esc(c.owner_username)} (ID ${c.owner_user_id}) · админы: ${(c.admin_user_ids||[]).join(', ')||'нет'}</div><div class="row"><input id="ct${c.id}" value="${esc(c.title)}" aria-label="Название"><input id="cu${c.id}" value="@${esc(c.username)}" aria-label="Username"><input id="co${c.id}" type="number" min="1" value="${c.owner_user_id}" aria-label="ID владельца"><button onclick="editChannel(${c.id})">Сохранить</button><button class="danger" onclick="deleteChannel(${c.id})">Удалить</button></div><div class="row"><input id="ca${c.id}" type="number" min="1" placeholder="ID пользователя для админа" aria-label="ID пользователя для админа"><button onclick="addChannelAdmin(${c.id})">Назначить админа</button><button class="danger" onclick="removeChannelAdmin(${c.id})">Снять админа по ID</button></div></div>`).join('')||'<small>Каналов пока нет.</small>'}catch(e){status(e.message)}}"""
replace_once(old_load, new_load, "channel list and role controls")

old_edit = """async function editChannel(id){try{await api('/api/admin/channels/'+id,'PATCH',{title:$('ct'+id).value,username:$('cu'+id).value});await loadChannels();status('Канал обновлён.')}catch(e){status(e.message)}}"""
new_edit = """async function editChannel(id){try{await api('/api/admin/channels/'+id,'PATCH',{title:$('ct'+id).value,username:$('cu'+id).value,owner_user_id:Number($('co'+id).value)});await loadChannels();status('Канал обновлён.')}catch(e){status(e.message)}}"""
replace_once(old_edit, new_edit, "channel owner edit")

admin_functions = """async function addChannelAdmin(id){try{const userId=Number($('ca'+id).value);if(!Number.isSafeInteger(userId)||userId<1)throw Error('Укажи корректный ID пользователя.');await api('/api/admin/channels/'+id+'/admins','POST',{user_id:userId});await loadChannels();status('Администратор канала назначен.')}catch(e){status(e.message)}}
async function removeChannelAdmin(id){try{const userId=Number($('ca'+id).value);if(!Number.isSafeInteger(userId)||userId<1)throw Error('Укажи корректный ID пользователя.');if(!confirm('Снять права администратора у пользователя ID '+userId+'?'))return;await api('/api/admin/channels/'+id+'/admins/'+userId,'DELETE');await loadChannels();status('Права администратора сняты.')}catch(e){status(e.message)}}"""
if "async function addChannelAdmin(" not in html:
    anchor = "async function deleteChannel(id){"
    pos = html.find(anchor)
    if pos < 0:
        raise SystemExit("Could not locate channel delete handler to add role functions")
    html = html[:pos] + admin_functions + "\n" + html[pos:]

page.write_text(html, encoding="utf-8")
print("WaysGram admin UI patched: test OTP display, owner reassignment, channel admin add/remove")
