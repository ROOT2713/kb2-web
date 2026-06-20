<template>
  <div class="methodology-page">
    <section class="hero card">
      <div>
        <span class="eyebrow">专题入口 · topic:data-methodology</span>
        <h1 class="page-title">数据生产方法库</h1>
        <p class="hero-copy">
          面向 kb2-web 的数据清洗、OCR/表单标注、标注质检与入库质量控制方法库。
          本页是索引和操作入口，详细内容以已入库文档和 RAG 查询结果为准。
        </p>
      </div>
      <RouterLink class="primary-link" :to="queryLink('数据生产方法库包含哪些能力')">
        查询能力总览
      </RouterLink>
    </section>

    <section class="grid two-cols">
      <article class="card method-card" v-for="section in methodSections" :key="section.title">
        <div class="card-head">
          <span class="icon">{{ section.icon }}</span>
          <h2>{{ section.title }}</h2>
        </div>
        <p>{{ section.summary }}</p>
        <ul>
          <li v-for="item in section.items" :key="item">{{ item }}</li>
        </ul>
      </article>
    </section>

    <section class="card">
      <div class="section-head">
        <div>
          <span class="eyebrow">Documents</span>
          <h2>已入库 12 份资料索引</h2>
        </div>
        <span class="badge">general bank</span>
      </div>
      <div class="doc-grid">
        <RouterLink
          v-for="doc in sourceDocs"
          :key="doc.id"
          class="doc-card"
          :to="`/documents/${doc.id}`"
        >
          <span class="doc-tag">{{ doc.group }}</span>
          <strong>{{ doc.title }}</strong>
          <small>{{ doc.note }}</small>
        </RouterLink>
      </div>
    </section>

    <section class="card">
      <div class="section-head">
        <div>
          <span class="eyebrow">RAG Prompts</span>
          <h2>推荐查询问题</h2>
        </div>
        <span class="hint">点击后跳转查询页并自动执行</span>
      </div>
      <div class="question-list">
        <RouterLink
          v-for="question in recommendedQuestions"
          :key="question"
          class="question-chip"
          :to="queryLink(question)"
        >
          {{ question }}
        </RouterLink>
      </div>
    </section>

    <section class="card note-card">
      <h2>使用边界</h2>
      <p>
        目前不新建独立 bank，不改 RAG 核心；当专题资料超过 30 份，或需要“只检索数据方法论”时，
        再评估迁移到 <code>data_production</code> / <code>methodology</code> bank。
      </p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { RouterLink } from 'vue-router'

interface MethodSection {
  icon: string
  title: string
  summary: string
  items: string[]
}

interface SourceDoc {
  id: string
  title: string
  group: string
  note: string
}

const methodSections: MethodSection[] = [
  {
    icon: '🧹',
    title: '数据清洗 SOP',
    summary: '从导入剖析到导出审计，形成可复用的清洗闭环。',
    items: ['导入数据并保留原始副本', 'Facet/Filter 定位异常', 'Cluster 归一化枚举', '导出前记录清洗日志'],
  },
  {
    icon: '✅',
    title: '结构化清洗 Checklist',
    summary: '按字段、类型、范围、重复、编码、日期等维度做入库前检查。',
    items: ['缺失值与默认值', '主键唯一性与重复记录', '日期/金额/编码格式', '输出字段可追溯'],
  },
  {
    icon: '🧰',
    title: '工具索引',
    summary: '把 OpenRefine、Pandas、Label Studio、OCR 工具按适用场景归档。',
    items: ['OpenRefine：交互式清洗', 'Pandas：脚本化批处理', 'Label Studio：标注任务配置', 'OCR：文档结构化入口'],
  },
  {
    icon: '📄',
    title: 'FUNSD Schema',
    summary: '表单理解标注的字段、框选、标签、链接关系参考模型。',
    items: ['question / answer / header / other', 'text、box、label、linking', '字段关系与阅读顺序', '困难样例和金标准样本'],
  },
  {
    icon: '🧪',
    title: '标注 QA 要点',
    summary: '从任务校准、金标准样本、抽检返工到规则更新的质量闭环。',
    items: ['试标校准', '自动检查 + 人工抽检', '问题分类与复训', '规则版本化更新'],
  },
  {
    icon: '🚦',
    title: 'P0-P3 质量门禁',
    summary: '按严重程度决定拒收、返工、局部修正或下批改进。',
    items: ['P0：致命，拒收整批', 'P1：严重，返工并扩抽', 'P2：一般，局部返工', 'P3：建议，下批改进'],
  },
]

const sourceDocs: SourceDoc[] = [
  { id: 'e4398255-d21f-4fd7-9136-4d8a2640cc8b', group: 'Label Studio', title: 'Label Studio 标注项目搭建 SOP(OCR/文档类)', note: 'OCR/文档类标注项目启动流程' },
  { id: '7554cced-82ee-448c-a691-a19c29e83702', group: 'Label Studio', title: 'OCR/文档标注模板库', note: '模板结构与字段配置参考' },
  { id: 'aef340d9-c18d-4789-a669-226b372be659', group: 'Data Quality', title: '政务数据质量六维度评估规则库', note: '完整性、唯一性、一致性等六维度' },
  { id: 'ac611c9e-b1ab-4755-801c-a2b4e01b8ef4', group: 'Data Quality', title: '数据质量评审检查清单', note: '入库前质量门禁检查表' },
  { id: '047e36ac-82dd-47b2-a0d7-5ca781123425', group: 'OpenRefine', title: 'OpenRefine GREL 与脏数据处理模式库', note: '常见脏数据转换模式' },
  { id: '30ee5f7e-9cec-4054-a759-ad9be4c936bd', group: 'OpenRefine', title: 'OpenRefine 数据清洗 SOP', note: '交互式清洗执行流程' },
  { id: 'fe883641-c948-406d-b928-9a01ca7d7bcb', group: 'QA Gate', title: '标注质检机制与质量门禁', note: 'P0-P3 门禁与返工策略' },
  { id: '8fcc80c7-bdf6-4eb0-8589-5d636e0b9783', group: 'CVAT QA', title: '标注质量保证通用流程(CVAT QA 启发)', note: '标注质量保证闭环' },
  { id: '87a68211-1c88-4d29-835a-c9b09c09c144', group: 'FUNSD', title: 'FUNSD 表单理解标注 Schema 解析', note: '表单理解 Schema 参考' },
  { id: 'b22d79fd-38ae-4733-bdca-301ad6df437e', group: 'FUNSD', title: 'OCR/表单标注样例库(FUNSD 启发)', note: '样例库与金标准建设' },
  { id: '197566a6-161b-4b9a-b85f-15e314c66d0d', group: 'Pandas', title: 'Pandas 清洗操作速查(Kaggle Data Cleaning 启发)', note: '脚本化清洗模式速查' },
  { id: '6a89a8bc-9bef-475e-a6b1-b2d5d053163c', group: 'Kaggle', title: '结构化数据清洗 Checklist(Kaggle Data Cleaning 启发)', note: '结构化数据清洗检查项' },
]

const recommendedQuestions = [
  '结构化数据清洗Checklist有哪些检查项',
  'OpenRefine数据清洗SOP怎么做',
  'OCR表单标注样例库怎么建设',
  'FUNSD表单理解标注Schema包含什么',
  '标注质检P0/P1/P2/P3怎么区分',
  'Label Studio OCR标注项目怎么搭建',
]

function queryLink(question: string) {
  return {
    path: '/query',
    query: {
      q: question,
      bank: 'general',
      autorun: '1',
    },
  }
}
</script>

<style scoped>
.methodology-page {
  max-width: 1180px;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.hero {
  display: flex;
  justify-content: space-between;
  gap: 1.5rem;
  align-items: flex-start;
  background: linear-gradient(135deg, white 0%, var(--accent-light) 100%);
}

.eyebrow {
  display: inline-block;
  font-size: 0.72rem;
  color: var(--accent);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 0.35rem;
}

.page-title {
  font-size: clamp(1.35rem, 2.4vw, 2rem);
  line-height: 1.2;
  margin-bottom: 0.6rem;
}

.hero-copy {
  color: var(--fg-muted);
  max-width: 760px;
}

.primary-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  white-space: nowrap;
  border: 1px solid var(--accent);
  background: var(--accent);
  color: white;
  padding: 0.55rem 0.8rem;
  text-decoration: none;
}

.primary-link:hover {
  background: var(--accent-hover);
  text-decoration: none;
}

.grid {
  display: grid;
  gap: 1rem;
}

.two-cols {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.method-card {
  min-height: 210px;
}

.card-head,
.section-head {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  align-items: flex-start;
  margin-bottom: 0.75rem;
}

.card-head {
  justify-content: flex-start;
  align-items: center;
}

.icon {
  font-size: 1.35rem;
}

h2 {
  font-size: 1rem;
  line-height: 1.3;
}

.method-card p,
.note-card p {
  color: var(--fg-muted);
  margin-bottom: 0.75rem;
}

ul {
  padding-left: 1.1rem;
}

li {
  margin-bottom: 0.25rem;
}

.doc-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.75rem;
}

.doc-card {
  border: 1px solid var(--border);
  background: var(--bg);
  padding: 0.75rem;
  min-height: 130px;
  color: var(--fg);
  text-decoration: none;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.doc-card:hover {
  border-color: var(--accent);
  background: white;
  text-decoration: none;
}

.doc-tag {
  align-self: flex-start;
  font-size: 0.68rem;
  color: var(--accent);
  border: 1px solid var(--accent-light);
  background: var(--accent-light);
  padding: 0.1rem 0.35rem;
}

.doc-card strong {
  font-size: 0.86rem;
  line-height: 1.35;
}

.doc-card small,
.hint {
  color: var(--fg-muted);
  font-size: 0.75rem;
}

.question-list {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.question-chip {
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--fg);
  padding: 0.45rem 0.65rem;
  font-size: 0.84rem;
  text-decoration: none;
}

.question-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: white;
  text-decoration: none;
}

code {
  font-family: var(--font-mono);
  font-size: 0.85em;
  background: var(--bg-alt);
  padding: 0.05rem 0.25rem;
}

@media (max-width: 960px) {
  .two-cols,
  .doc-grid {
    grid-template-columns: 1fr;
  }

  .hero,
  .section-head {
    flex-direction: column;
  }
}
</style>
