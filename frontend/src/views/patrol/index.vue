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
      <article v-for="item in stats" :key="item.label" class="stat-card">
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
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
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
      <span>共 {{ total }} 条巡视检查记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { fetchJson, request } from '@/api/client'

type Row = Record<string, string | number | null>
type StatCard = { label: string; value: number }

const ENDPOINT = '/api/patrol'
const columns = ["巡视单号", "巡视路线", "巡视人员", "巡视日期", "发现问题数", "整改项数", "巡视时长", "超时标记", "巡视状态"]
const actions = ["派发巡视", "提交结果", "作废巡视"]
const statuses = ["待派发", "巡视中", "已提交", "已作废"]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<StatCard[]>([])
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
  const values: Record<string, string> = { action }
  if (action === '提交结果') {
    const found = window.prompt('本次巡视发现问题数（非负整数）', String(row['发现问题数'] ?? 0))
    if (found === null) return
    const fixed = window.prompt('其中需整改的项数（非负整数）', String(row['整改项数'] ?? 0))
    if (fixed === null) return
    const hours = window.prompt('巡视时长（小时，可留空）', String(row['巡视时长'] ?? ''))
    if (hours === null) return
    values['发现问题数'] = found
    values['整改项数'] = fixed
    if (hours.trim() !== '') {
      values['巡视时长'] = hours
    }
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const result = await response.json()
    if (!response.ok || !result.ok) {
      throw new Error(result.message || '巡视检查动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡视检查操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const [listPayload, statsPayload] = await Promise.all([
      fetchJson<{ items?: Row[]; total?: number }>(`${ENDPOINT}?${query}`),
      fetchJson<{ cards?: StatCard[] }>(`${ENDPOINT}/stats`),
    ])
    rows.value = listPayload.items ?? []
    total.value = listPayload.total ?? rows.value.length
    stats.value = statsPayload.cards ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡视检查数据读取失败'
  }
}

onMounted(reload)
</script>
