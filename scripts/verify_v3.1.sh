TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsImlhdCI6MTc4NDg5MzY1MCwiZXhwIjoxNzg0OTgwMDUwfQ.-alLXA59isoA6853sCgIZXMDQaOD1Pbj3nkQDJZPXJY"

echo "=== 1. Wiki search: 声环境 ==="
curl -s -G -H "Authorization: Bearer $TOKEN" "http://localhost:3027/api/wiki/search" \
  --data-urlencode "q=声环境" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'total={d[\"total\"]} items={[i[\"title\"] for i in d[\"items\"]]}')"

echo "=== 2. Wiki entry detail (声环境) ==="
curl -s -H "Authorization: Bearer $TOKEN" "http://localhost:3027/api/wiki/entry/4" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'{d[\"title\"]} ({d[\"standard_no\"]}) summary={d.get(\"summary\",\"\")[:50]}')"

echo "=== 3. F05: 声环境质量标准 (退化修复) ==="
curl -s -X POST http://localhost:3027/api/query \
  -H "Authorization: Bearer $TOKEN" \
  -F "q=声环境质量标准的国家标准编号是什么？" -F "bank=all" -F "nocache=true" -m 180 | python3 -c "import sys,json; d=json.load(sys.stdin); ans=d.get('answer',''); print(f'ans={len(ans)}字 gb3096={\"3096\" in ans} 声环境={\"声环境\" in ans}')"

echo "=== 4. F01: 数据中心温度 ==="
curl -s -X POST http://localhost:3027/api/query \
  -H "Authorization: Bearer $TOKEN" \
  -F "q=数据中心机房温度要求范围是多少？" -F "bank=all" -F "nocache=true" -m 180 | python3 -c "import sys,json; d=json.load(sys.stdin); ans=d.get('answer',''); print(f'ans={len(ans)}字 gb50174={\"50174\" in ans} 24={\"24\" in ans}')"

echo "=== 5. etc 安全 ==="
curl -s -X POST http://localhost:3027/api/query \
  -H "Authorization: Bearer $TOKEN" \
  -F "q=网络安全等级保护基本要求的国家标准编号是什么？" -F "bank=all" -F "nocache=true" -m 180 | python3 -c "import sys,json; d=json.load(sys.stdin); ans=d.get('answer',''); print(f'ans={len(ans)}字 gbt22239={\"22239\" in ans}')"

echo "=== 6. Frontend wiki route ==="
curl -s -o /dev/null -w "wiki-entries page status=%{http_code}" http://localhost:3027/wiki-entries
echo ""
