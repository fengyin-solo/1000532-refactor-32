<template>
  <section class="page" data-module="patrol">
    <header class="page-head">
      <div>
        <h2>巡视检查管理</h2>
        <p class="page-desc">维护巡视单，围绕巡视单号、巡视路线、巡视人员、巡视日期做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记巡视单</button>
        <button class="btn" type="button" @click="exportRows">导出巡视检查清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card" :class="{ 'stat-warn': item.label === '超时巡视' && item.value > 0 }">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ 'row-timeout': row.超时 }">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '巡视时长'">
              <span v-if="Number(row[column]) > 0">{{ row[column] }} 分钟</span>
              <span v-else>—</span>
              <span v-if="row.超时" class="badge-warn" title="超过巡视时长上限 240 分钟">超时</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无巡视检查数据，可先登记巡视单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条巡视检查记录（已作废巡视单不参与上方合计）</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>
type StatCard = { label: string; value: number }

const ENDPOINT = '/api/patrol'
const columns = ["巡视单号", "巡视路线", "巡视人员", "巡视日期", "发现问题数", "整改项数", "巡视时长", "巡视状态"]
const actions = ["派发巡视", "提交结果", "作废巡视"]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<StatCard[]>([
  { label: "待派发巡视", value: 0 },
  { label: "巡视中任务", value: 0 },
  { label: "本月发现问题", value: 0 },
  { label: "本月整改项", value: 0 },
  { label: "超时巡视", value: 0 },
])
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '巡视单登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('巡视检查动作未生效，请稍后重试')
    }
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '巡视检查动作未生效')
    }
    await Promise.all([reload(), reloadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡视检查操作失败'
  }
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      return
    }
    const payload = await response.json()
    if (Array.isArray(payload.cards)) {
      stats.value = payload.cards
    }
  } catch {
    // 统计读不到时保留上一次结果，不影响列表操作
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('巡视单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡视检查列表读取失败'
  }
}

onMounted(() => {
  void reload()
  void reloadStats()
})
</script>

<style scoped>
.badge-warn {
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 4px;
  font-size: 12px;
  line-height: 18px;
  color: #b42318;
  background: #fee4e2;
  border: 1px solid #fda29b;
}

.row-timeout {
  background: #fff7ed;
}

.row-timeout:hover td {
  background: #ffedd5;
}

.stat-warn .stat-value {
  color: #b42318;
}
</style>
