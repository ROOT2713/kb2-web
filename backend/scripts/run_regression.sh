"""
kb2-web 回归测试运行器 — 一站式质量检查

用法:
  ./run_regression.sh                           # 单元级回归（快速，不依赖产线 DB）
  ./run_regression.sh full                      # 全量单元回归（数据完整性 + 缓存 + 检索 + 合同）
  ./run_regression.sh baseline                  # 全量回归 + 基线快照（需要产线 DB + Hindsight）
  ./run_regression.sh compare                   # 对比当前 vs 基线（改造前后对比）
  ./run_regression.sh errors                    # 错题报告
  ./run_regression.sh list                      # 列出所有测试模块
"""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SCRIPT_DIR")"
cd "$BACKEND_DIR" || exit 1

. /home/ubuntu/.hermes/hermes-agent/venv/bin/activate
export PYTHONPATH="$BACKEND_DIR:$PYTHONPATH"

MODE="${1:-unit}"

# ── 可用的测试模块（标记 @integration = 需要产线DB） ──
UNIT_TESTS=(
  "tests/unit/test_regression_retrieval.py -k 'not TestGoldenQuery'"
  "tests/unit/test_data_integrity.py"
  "tests/unit/test_cache_mechanisms.py"
  "tests/unit/test_frontend_endpoints.py -k 'not TestAPIEndpointAvailability and not TestFrontendPageLoad and not TestAPIResponseShape'"
)

INTEGRATION_TESTS=(
  "tests/unit/test_frontend_endpoints.py -k 'not TestQueryWorkflow' --run-integration"
  "tests/unit/test_regression_retrieval.py -k 'TestGoldenQuery' --run-integration"
)

case "$MODE" in
  unit)
    echo ">>> 单元回归: 检索 + 数据完整性 + 缓存 + 合同结构"
    FAILED=0
    for spec in "${UNIT_TESTS[@]}"; do
      echo ""
      echo "--- pytest $spec ---"
      python3 -m pytest $spec -v --tb=short || FAILED=$((FAILED + 1))
    done
    echo ""
    if [ "$FAILED" -eq 0 ]; then
      echo "✅ 全部单元测试通过"
    else
      echo "❌ $FAILED 个测试模块有失败"
    fi
    exit $FAILED
    ;;

  full)
    echo ">>> 全量单元回归（含所有模块）"
    python3 -m pytest tests/unit/ -v --tb=short --ignore=tests/unit/test_regression_retrieval.py || true
    python3 -m pytest tests/unit/test_regression_retrieval.py -v --tb=short \
      -k "not TestGoldenQuery" || true
    echo ""
    echo ">>> 错题报告"
    python3 scripts/wrong_answers.py report
    ;;

  baseline)
    echo ">>> Step 1: 单元级回归"
    for spec in "${UNIT_TESTS[@]}"; do
      echo "--- pytest $spec ---"
      python3 -m pytest $spec -v --tb=short || true
    done

    echo ""
    echo ">>> Step 2: 全量回归 + 基线快照（需要产线 DB + Hindsight + 3027）"
    SNAPSHOT_DIR="$BACKEND_DIR/regression_snapshots"
    mkdir -p "$SNAPSHOT_DIR"
    python3 -m pytest tests/unit/test_regression_retrieval.py -v --tb=short \
      --run-integration -k "TestGoldenQuery" || true

    for spec in "${INTEGRATION_TESTS[@]}"; do
      echo "--- pytest $spec ---"
      python3 -m pytest $spec -v --tb=short || true
    done

    echo ""
    echo ">>> 基线快照已保存到: $SNAPSHOT_DIR"
    echo "    改造后: $0 compare"
    echo ""
    python3 scripts/wrong_answers.py report
    ;;

  compare)
    echo ">>> 对比当前 vs 基线"
    python3 scripts/compare_regression.py
    ;;

  errors)
    echo ">>> 错题管理"
    python3 scripts/wrong_answers.py "${@:2}"
    ;;

  list)
    echo "测试模块清单："
    echo ""
    echo "  单元测试（本地可跑）:"
    echo "    test_regression_retrieval.py  — 黄金查询集的单元级 + 查询集完整性"
    echo "    test_data_integrity.py        — DB 数据完整性（引用/字段/一致性/时效）"
    echo "    test_cache_mechanisms.py      — L1/L2/BM25 缓存行为"
    echo "    test_frontend_endpoints.py    — API 响应结构 + 前端合同"
    echo ""
    echo "  集成测试（需要产线 DB + 3027）:"
    echo "    test_golden_query             — 22 条黄金查询端到端检索"
    echo "    test_api_endpoints            — API 端点可用性"
    echo "    test_frontend_pages           — 前端页面 HTML 加载"
    echo "    test_query_workflow           — 查询→检索→回答工作流"
    echo ""
    echo "  工具脚本:"
    echo "    scripts/wrong_answers.py      — 错题积累/报告/验证"
    echo "    scripts/compare_regression.py — 基线 vs 当前对比"
    echo "    scripts/run_regression.sh     — 运行器"
    echo ""
    echo "  错题: tests/errors/errors.json"
    echo "  快照: regression_snapshots/"
    ;;

  *)
    echo "未知模式: $MODE"
    echo "用法: $0 [unit|full|baseline|compare|errors|list]"
    exit 1
    ;;
esac
