#!/bin/bash
# surgical_retrieval_fix.sh — 修复 retrieval.py 中 5 处变量名遮蔽
# 根因: `text = r.get("text","")` 覆盖了顶层 `from sqlalchemy import text`
# 影响: build_bm25_index() 中 text("""...""") 变成对字符串调用 → TypeError
# 方案: 所有 `text` 局部变量改名为 `mem_text`，sqlalchemy.text 保持不变

set -euo pipefail
TARGET="/home/ubuntu/kb2-web/backend/app/services/retrieval.py"
BACKUP="/home/ubuntu/kb2-web/backend/app/services/retrieval.py.bak.$(date +%s)"
cp "$TARGET" "$BACKUP"
echo "✅ 备份: $BACKUP"

cd /home/ubuntu/kb2-web/backend

# ── Patch 1: build_bm25_index() L310-323 ──
# text → mem_text (5处引用)
python3 -c "
import re
with open('$TARGET', 'r') as f:
    lines = f.readlines()

changes = 0

# L310: text = r.get('text', '') or ''
# L311: if not text.strip():
# L313: dedup_key = text[:80]
# L323: docs.append({'text': text, ...})
# These are in lines 309-323 (0-indexed: 308-322)
for i in range(308, 325):
    if i < len(lines):
        old = lines[i]
        # Only replace standalone 'text' used as variable, not dict keys or imports
        new = old
        # Pattern: text at start of expression (not inside dict/string)
        new = new.replace('text = r.get', 'mem_text = r.get')
        new = new.replace('if not text.strip', 'if not mem_text.strip')
        new = new.replace('dedup_key = text[:', 'dedup_key = mem_text[:')
        # docs.append line: only replace 'text' as the value, not the key 'text':
        new = new.replace(\"'text': text}\", \"'text': mem_text}\")
        if new != old:
            lines[i] = new
            changes += 1

# ── Patch 2: _make_key() L422 ──
# text = r.get('text', '')[:80]
# return f\"{doc_id or 'x'}_{text}\"
for i in range(420, 425):
    if i < len(lines):
        old = lines[i]
        new = old.replace('text = r.get', 'mem_text = r.get')
        new = new.replace('}_{text}', '}_{mem_text}')
        if new != old:
            lines[i] = new
            changes += 1

# ── Patch 3: rrf_merge() BM25 block L436-441 ──
# text = r.get('text', '')
# if query_keywords and any(kw in text ...)
# if any(kw in text ...)
for i in range(434, 445):
    if i < len(lines):
        old = lines[i]
        new = old.replace('text = r.get', 'mem_text = r.get')
        new = new.replace('kw in text)', 'kw in mem_text)')
        if new != old:
            lines[i] = new
            changes += 1

# ── Patch 4: rrf_merge() doc keyword density L464-465 ──
# text = item.get('text', '')
# hits = sum(1 for kw in query_keywords if kw in text)
for i in range(462, 468):
    if i < len(lines):
        old = lines[i]
        new = old.replace('text = item.get', 'mem_text = item.get')
        new = new.replace('if kw in text)', 'if kw in mem_text)')
        if new != old:
            lines[i] = new
            changes += 1

# ── Patch 5: llm_rerank() L521-531 ──
# text = c.get('text', '')[:500].replace(...)
# snippets.append(f'[{i}] {title_prefix}{text}')
for i in range(519, 533):
    if i < len(lines):
        old = lines[i]
        new = old.replace('text = c.get', 'mem_text = c.get')
        new = new.replace('{title_prefix}{text}', '{title_prefix}{mem_text}')
        if new != old:
            lines[i] = new
            changes += 1

with open('$TARGET', 'w') as f:
    f.writelines(lines)
print(f'✅ {changes} 处变量名 text → mem_text')
"

# ── 验证: 没有遗漏的遮蔽 ──
echo ""
echo "=== 验证: 仍使用 text= 的行（应该只剩 import 和 dict key） ==="
grep -n "^\s*text\s*=" "$TARGET" || echo "(无)"

echo ""
echo "=== 验证: sqlalchemy.text() 调用仍完整 ==="
grep -n "text(" "$TARGET" | grep -v "parent_text\|mem_text\|#\|\.text\|'text'" | head -10

echo ""
echo "=== 语法检查 ==="
/home/ubuntu/.hermes/hermes-agent/venv/bin/python3 -c "import py_compile; py_compile.compile('$TARGET', doraise=True); print('✅ 语法正确')"

echo ""
echo "=== 重启服务 ==="
sudo systemctl restart kb2-web
echo "等待启动..."
sleep 8
curl -s http://localhost:3027/health

echo ""
echo "=== 检查 BM25 日志 ==="
sudo journalctl -u kb2-web.service --since "30 seconds ago" --no-pager 2>/dev/null | grep -i "BM25\|startup\|error" | tail -10
