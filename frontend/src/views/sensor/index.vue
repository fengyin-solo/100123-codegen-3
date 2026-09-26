<template>
  <section class="page" data-module="sensor">
    <header class="page-head">
      <div>
        <h2>温感器管理</h2>
        <p class="page-desc">
          校准口径：下次校准日距今天不足阈值自动标待校准（默认 30 天，FLEE-0001 提前 45 天、FLEE-0003 提前 15 天）；
          电量不足与已停用不参与判定；精度等级不符仍在用的一律拦下。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="toggleCreate">登记温度传感器</button>
        <button class="btn" type="button" @click="exportRows">导出温感器管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card" :class="item.tone">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showCreate" class="create-panel" @submit.prevent="submitCreate">
      <label v-for="field in createFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input
          v-model="createForm[field]"
          :placeholder="field.includes('日期') || field.includes('校准日') ? 'YYYY-MM-DD' : `请输入${field}`"
        />
      </label>
      <div class="create-actions">
        <button class="btn primary" type="submit">保存</button>
        <button class="btn ghost" type="button" @click="toggleCreate">取消</button>
      </div>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>传感器编号</span>
        <input v-model="keyword" placeholder="按传感器编号检索" />
      </label>
      <label class="filter-item">
        <span>传感器状态</span>
        <select v-model="statusFilter">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
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
        <tr v-for="row in rows" :key="String(row.id)" :class="rowClass(row)">
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
          <td :colspan="columns.length + 1" class="empty-state">暂无温感器管理数据，可先登记温度传感器</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条温感器管理记录</span>
      <span v-if="infoMessage" class="info-text">{{ infoMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/sensor'
const columns = ["传感器编号", "所属车辆", "传感器型号", "精度等级", "校准日期", "下次校准日", "电池电量", "传感器状态", "校准结论"]
const actions = ["偏移预警", "安排校准", "停用传感器"]
const statuses = ["正常", "数据偏移", "待校准", "已停用"]
const createFields = ["传感器编号", "所属车辆", "传感器型号", "精度等级", "校准日期", "下次校准日", "电池电量"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const infoMessage = ref('')
const keyword = ref('')
const statusFilter = ref('')
const showCreate = ref(false)
const createForm = ref<Record<string, string>>({})
const stats = ref([
  { label: '正常传感器', value: 0, tone: '' },
  { label: '待校准传感器', value: 0, tone: 'warn' },
  { label: '精度拦截', value: 0, tone: 'danger' },
  { label: '已停用', value: 0, tone: '' },
])

function rowClass(row: Row) {
  return {
    'row-blocked': row['精度拦截'] === true,
    'row-due': row['精度拦截'] !== true && row['status'] === '待校准',
  }
}

function toggleCreate() {
  showCreate.value = !showCreate.value
  errorMessage.value = ''
  infoMessage.value = ''
  if (showCreate.value) {
    createForm.value = {}
  }
}

function resetFilters() {
  keyword.value = ''
  statusFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function readResult(response: Response, fallback: string) {
  const payload = await response.json().catch(() => null)
  if (!response.ok || !payload || payload.ok === false) {
    throw new Error(payload?.message ?? payload?.detail ?? fallback)
  }
  return payload
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  infoMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await readResult(response, '温感器管理动作未生效，请稍后重试')
    infoMessage.value = payload.message ?? ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '温感器管理操作失败'
  }
}

async function submitCreate() {
  errorMessage.value = ''
  infoMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await readResult(response, '温度传感器保存失败')
    infoMessage.value = payload.message ?? '温度传感器已登记'
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '温度传感器保存失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (keyword.value.trim()) query.set('keyword', keyword.value.trim())
  if (statusFilter.value) query.set('status', statusFilter.value)
  try {
    const [listResponse, summaryResponse] = await Promise.all([
      request(`${ENDPOINT}?${query.toString()}`),
      request(`${ENDPOINT}/summary`),
    ])
    const payload = await listResponse.json()
    if (!listResponse.ok) {
      throw new Error('温度传感器列表读取失败')
    }
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (summaryResponse.ok) {
      const summary = await summaryResponse.json()
      const counts = summary.status_counts ?? {}
      stats.value = [
        { label: '正常传感器', value: counts['正常'] ?? 0, tone: '' },
        { label: '待校准传感器', value: counts['待校准'] ?? 0, tone: 'warn' },
        { label: '精度拦截', value: summary['精度拦截'] ?? 0, tone: 'danger' },
        { label: '已停用', value: counts['已停用'] ?? 0, tone: '' },
      ]
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '温感器管理列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.create-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: flex-end;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}
.create-panel .filter-item span {
  display: block;
  font-size: 12px;
  color: var(--muted);
}
.create-actions {
  display: flex;
  gap: 8px;
}
.filter-item select,
.filter-item input {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
}
.row-due td {
  background: #fff7ed;
}
.row-blocked td {
  background: #fef2f2;
}
.stat-card.warn .stat-value {
  color: #b45309;
}
.stat-card.danger .stat-value {
  color: #b42318;
}
.info-text {
  color: #15803d;
}
</style>
