#!/bin/bash
# A/B comparison test: v1 vs v2

V1="http://localhost:3002"
V2="http://localhost:3027"

# Login to v2
TOKEN=$(curl -s -X POST "$V2/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"adminljj0806!"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('token',''))")

echo "V2 Token: ${TOKEN:0:20}..."

QUERIES=(
  "知识库系统"
  "验收测评服务规范"
  "GB/T 22239 等保测评"
  "500万软件项目的取费标准"
  "政务信息化项目管理办法"
  "电子会议系统工程施工"
  "数据中心基础设施"
  "信息安全等级保护"
  "软件造价评估方法"
  "安防工程设计施工规范"
)

echo "=== RESULTS_START ==="

for i in "${!QUERIES[@]}"; do
  Q="${QUERIES[$i]}"
  echo "--- QUERY $i: $Q ---"
  
  # V1 test
  V1_START=$(date +%s%N)
  V1_RESP=$(curl -s -w "\n%{http_code}\n%{time_total}" -X POST "$V1/api/query" \
    -d "q=$Q&bank=all" 2>/dev/null)
  V1_END=$(date +%s%N)
  
  V1_BODY=$(echo "$V1_RESP" | head -n -2)
  V1_CODE=$(echo "$V1_RESP" | tail -n 2 | head -n 1)
  V1_TIME=$(echo "$V1_RESP" | tail -n 1)
  
  # Count results
  V1_COUNT=$(echo "$V1_BODY" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin)
  if isinstance(d,dict) and 'results' in d: print(len(d['results']))
  elif isinstance(d,dict) and 'data' in d:
    dd=d['data']
    if isinstance(dd,dict) and 'results' in dd: print(len(dd['results']))
    elif isinstance(dd,list): print(len(dd))
    else: print('0')
  elif isinstance(d,list): print(len(d))
  else: print('0')
except: print('error')
" 2>/dev/null)
  
  V1_SNIPPET=$(echo "$V1_BODY" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin)
  r=None
  if isinstance(d,dict) and 'results' in d: r=d['results']
  elif isinstance(d,dict) and 'data' in d:
    dd=d['data']
    if isinstance(dd,dict) and 'results' in dd: r=dd['results']
    elif isinstance(dd,list): r=dd
  if r and len(r)>0:
    item=r[0]
    title=item.get('title',item.get('name',''))
    print(title[:80])
  else: print('N/A')
except: print('N/A')
" 2>/dev/null)
  
  # V2 test
  V2_RESP=$(curl -s -w "\n%{http_code}\n%{time_total}" -X POST "$V2/api/query" \
    -H "Authorization: Bearer $TOKEN" \
    -d "q=$Q&bank=all&nocache=true" 2>/dev/null)
  
  V2_BODY=$(echo "$V2_RESP" | head -n -2)
  V2_CODE=$(echo "$V2_RESP" | tail -n 2 | head -n 1)
  V2_TIME=$(echo "$V2_RESP" | tail -n 1)
  
  V2_COUNT=$(echo "$V2_BODY" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin)
  if isinstance(d,dict) and 'results' in d: print(len(d['results']))
  elif isinstance(d,dict) and 'data' in d:
    dd=d['data']
    if isinstance(dd,dict) and 'results' in dd: print(len(dd['results']))
    elif isinstance(dd,list): print(len(dd))
    else: print('0')
  elif isinstance(d,list): print(len(d))
  else: print('0')
except: print('error')
" 2>/dev/null)
  
  V2_SNIPPET=$(echo "$V2_BODY" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin)
  r=None
  if isinstance(d,dict) and 'results' in d: r=d['results']
  elif isinstance(d,dict) and 'data' in d:
    dd=d['data']
    if isinstance(dd,dict) and 'results' in dd: r=dd['results']
    elif isinstance(dd,list): r=dd
  if r and len(r)>0:
    item=r[0]
    title=item.get('title',item.get('name',''))
    print(title[:80])
  else: print('N/A')
except: print('N/A')
" 2>/dev/null)
  
  echo "V1|${V1_CODE}|${V1_TIME}|${V1_COUNT}|${V1_SNIPPET}"
  echo "V2|${V2_CODE}|${V2_TIME}|${V2_COUNT}|${V2_SNIPPET}"
  
  # Compare top results
  V1_TOP=$(echo "$V1_BODY" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin)
  r=None
  if isinstance(d,dict) and 'results' in d: r=d['results']
  elif isinstance(d,dict) and 'data' in d:
    dd=d['data']
    if isinstance(dd,dict) and 'results' in dd: r=dd['results']
    elif isinstance(dd,list): r=dd
  if r:
    for item in r[:3]:
      t=item.get('title',item.get('name',''))
      print(t)
except: pass
" 2>/dev/null)
  
  V2_TOP=$(echo "$V2_BODY" | python3 -c "
import sys,json
try:
  d=json.load(sys.stdin)
  r=None
  if isinstance(d,dict) and 'results' in d: r=d['results']
  elif isinstance(d,dict) and 'data' in d:
    dd=d['data']
    if isinstance(dd,dict) and 'results' in dd: r=dd['results']
    elif isinstance(dd,list): r=dd
  if r:
    for item in r[:3]:
      t=item.get('title',item.get('name',''))
      print(t)
except: pass
" 2>/dev/null)
  
  echo "V1_TOP3<<EOF"
  echo "$V1_TOP"
  echo "EOF"
  echo "V2_TOP3<<EOF"
  echo "$V2_TOP"
  echo "EOF"
done

echo "=== RESULTS_END ==="
