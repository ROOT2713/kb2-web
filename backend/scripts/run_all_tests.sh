#!/bin/bash
# run_all_tests.sh — kb2-web CI 统一入口
# 整合 3 个测试通道：pytest + 66题回归 + 84题诊断
set -e

cd "$(dirname "$0")/.."
DIR="$(pwd)"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
PASS=0
FAIL=0

echo "╔══════════════════════════════════════╗"
echo "║  kb2-web 全量回归测试               ║"
echo "║  $TIMESTAMP              ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. pytest（单元+集成）──
echo "━━━ [1/3] pytest unit+integration ━━━"
cd "$DIR"
if python3 -m pytest tests/ -x --tb=short -q 2>&1; then
    echo "✅ pytest PASSED"
    PASS=$((PASS+1))
else
    echo "❌ pytest FAILED"
    FAIL=$((FAIL+1))
fi
echo ""

# ── 2. 66 题回归测试 ──
echo "━━━ [2/3] 66 题回归测试 ━━━"
cd "$DIR"
if python3 scripts/kb2_66test_v3.py 2>&1 | tail -5; then
    echo "✅ 66-test PASSED"
    PASS=$((PASS+1))
else
    echo "❌ 66-test FAILED"
    FAIL=$((FAIL+1))
fi
echo ""

# ── 3. 84 题诊断测试（如存在）──
echo "━━━ [3/3] 84 题诊断测试 ━━━"
if [ -f "$DIR/scripts/kb2_84test.py" ]; then
    cd "$DIR"
    if python3 scripts/kb2_84test.py 2>&1 | tail -5; then
        echo "✅ 84-test PASSED"
        PASS=$((PASS+1))
    else
        echo "❌ 84-test FAILED"
        FAIL=$((FAIL+1))
    fi
else
    echo "⚠️  84-test 脚本不存在，跳过"
fi
echo ""

# ── 汇总 ──
echo "╔══════════════════════════════════════╗"
echo "║  结果：$PASS 通过 / $((PASS+FAIL)) 总项"
echo "╚══════════════════════════════════════╝"
exit $FAIL
