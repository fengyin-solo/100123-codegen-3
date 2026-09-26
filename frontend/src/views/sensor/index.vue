<template>
  <section class="page" data-module="sensor">
    <header class="page-head">
      <div>
        <h2>温感器管理</h2>
        <p class="page-desc">
          按新校准口径自动判定：距下次校准日不足所属车辆阈值的传感器自动标为待校准；
          电量不足与已停用不参与到期判定；精度等级不符车辆要求且在用的禁止登记校准并拦截使用。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记温度传感器</button>
        <button class="btn" type="button" @click="exportRows">导出温感器清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value" :class="statClass(item.label)">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>传感器编号</span>
        <input v-model="filters.keyword" placeholder="按传感器编号检索" />
      </label>
      <label class="filter-item">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>校准判定</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="rowClass(row)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>
            <span class="badge" :class="badgeClass(row)">{{ verdictLabel(row) }}</span>
            <p v-if="row['判定说明']" class="cell-tip" :title="String(row['判定说明'] ?? '')">{{ row['判定说明'] }}</p>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看详情</button>
            <button class="link" type="button" @click="openCalibration(row)">登记校准</button>
            <button
              v-for="action in manualActions(row)"
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
          <td :colspan="columns.length + 2" class="empty-state">暂无温感器数据，可先登记温度传感器</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条温感器记录，结论由同一套规则实时计算，台账与详情一致</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 传感器详情：展示字段与台账同一份后端视图，结论不会出现两个口径 -->
    <div v-if="detailRow" class="modal-mask" @click.self="detailRow = null">
      <div class="modal">
        <div class="modal-head">
          <h3>传感器详情 · {{ detailRow['传感器编号'] }}</h3>
          <button class="link" type="button" @click="detailRow = null">关闭</button>
        </div>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd>{{ detailRow[field] ?? '—' }}</dd>
          </template>
          <dt>校准判定</dt>
          <dd>
            <span class="badge" :class="badgeClass(detailRow)">{{ verdictLabel(detailRow) }}</span>
            <span v-if="verdictLabel(detailRow) !== detailRow['校准判定']" class="verdict-note">
              （校准口径：{{ detailRow['校准判定'] }}）
            </span>
          </dd>
          <dt>判定说明</dt>
          <dd class="reason-cell">{{ detailRow['判定说明'] }}</dd>
        </dl>
      </div>
    </div>

    <!-- 登记校准：日期倒挂、精度不符会被后端拦下，原因直接展示在弹窗里 -->
    <div v-if="calibrationOpen" class="modal-mask" @click.self="calibrationOpen = false">
      <div class="modal">
        <div class="modal-head">
          <h3>登记校准记录{{ calibrationForm.传感器编号 ? ` · ${calibrationForm.传感器编号}` : '' }}</h3>
          <button class="link" type="button" @click="calibrationOpen = false">关闭</button>
        </div>
        <form class="modal-form" @submit.prevent="submitCalibration">
          <label v-if="!calibrationForm.传感器编号">
            <span>传感器编号 *</span>
            <input v-model="calibrationForm.传感器编号" required />
          </label>
          <label>
            <span>校准日期 *</span>
            <input v-model="calibrationForm.校准日期" type="date" required />
          </label>
          <label>
            <span>下次校准日 *</span>
            <input v-model="calibrationForm.下次校准日" type="date" required />
          </label>
          <label>
            <span>精度等级 *</span>
            <select v-model="calibrationForm.精度等级" required>
              <option value="" disabled>请选择</option>
              <option value="A级">A级</option>
              <option value="B级">B级</option>
              <option value="C级">C级</option>
            </select>
          </label>
          <label>
            <span>电池电量（%）</span>
            <input v-model="calibrationForm.电池电量" type="number" min="0" max="100" />
          </label>
          <p class="form-hint">
            保存规则：校准日期不得晚于下次校准日；精度等级不符所属车辆要求且传感器在用的，数据不予保存。
            同一传感器编号多次校准时以最近一次为准。
          </p>
          <p v-if="calibrationError" class="error-text">{{ calibrationError }}</p>
          <div class="modal-actions">
            <button class="btn" type="button" @click="calibrationOpen = false">取消</button>
            <button class="btn primary" type="submit">保存校准记录</button>
          </div>
        </form>
      </div>
    </div>

    <!-- 登记新传感器 -->
    <div v-if="createOpen" class="modal-mask" @click.self="createOpen = false">
      <div class="modal">
        <div class="modal-head">
          <h3>登记温度传感器</h3>
          <button class="link" type="button" @click="createOpen = false">关闭</button>
        </div>
        <form class="modal-form" @submit.prevent="submitCreate">
          <label v-for="field in createFields" :key="field">
            <span>{{ field }} *</span>
            <input v-model="createForm[field]" required />
          </label>
          <p v-if="createError" class="error-text">{{ createError }}</p>
          <div class="modal-actions">
            <button class="btn" type="button" @click="createOpen = false">取消</button>
            <button class="btn primary" type="submit">保存</button>
          </div>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/sensor'
const CALIBRATION_ENDPOINT = '/api/calibration'
const columns = ['传感器编号', '所属车辆', '传感器型号', '精度等级', '校准日期', '下次校准日', '电池电量', '传感器状态']
const statuses = ['正常', '数据偏移', '待校准', '已停用']
const createFields = ['传感器编号', '所属车辆', '传感器型号']
const detailFields = [
  '传感器编号', '所属车辆', '传感器型号', '精度等级', '校准日期', '下次校准日',
  '电池电量', '传感器状态', '到期阈值', '距到期天数',
]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<{ label: string; value: number }[]>([])
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = reactive<{ keyword: string; status: string }>({ keyword: '', status: '' })

const detailRow = ref<Row | null>(null)
const createOpen = ref(false)
const createError = ref('')
const createForm = reactive<Record<string, string>>({})

const calibrationOpen = ref(false)
const calibrationError = ref('')
const calibrationForm = reactive<Record<string, string>>({ 传感器编号: '', 校准日期: '', 下次校准日: '', 精度等级: '', 电池电量: '' })

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function verdictLabel(row: Row): string {
  const verdict = String(row['校准判定'] ?? '')
  // 校准本身正常但人工已报数据偏移时，优先暴露更需要处理的状态
  if (verdict === '正常' && row.status === '数据偏移') return '数据偏移'
  return verdict || String(row.status ?? '—')
}

function badgeClass(row: Row): string {
  const label = verdictLabel(row)
  if (label === '待校准') return 'badge-due'
  if (label === '精度不符') return 'badge-block'
  if (label === '已停用') return 'badge-off'
  if (label === '数据偏移') return 'badge-offset'
  if (label === '低电量免判') return 'badge-warn'
  if (label === '无校准计划') return 'badge-warn'
  return 'badge-ok'
}

function rowClass(row: Row): Record<string, boolean> {
  return {
    'row-due': verdictLabel(row) === '待校准',
    'row-block': verdictLabel(row) === '精度不符',
  }
}

function statClass(label: string): string {
  if (label.includes('待校准')) return 'stat-danger'
  if (label.includes('精度不符')) return 'stat-danger'
  if (label.includes('低电量')) return 'stat-warn'
  return ''
}

function manualActions(row: Row): string[] {
  if (row.status === '已停用') return []
  // 精度不符在用时，「安排校准」会被后端硬拦截，前端直接不展示；只能补合格校准记录或停用
  if (row['精度不符']) return ['偏移预警', '停用传感器']
  // 临期时仍允许人工处理，但校准动作不会冲掉规则结论
  return ['偏移预警', '安排校准', '停用传感器']
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (response.ok) {
      const payload = await response.json()
      stats.value = payload.cards ?? []
    }
  } catch {
    // 卡片加载失败不阻断台账列表
  }
}

async function reload() {
  errorMessage.value = ''
  noticeMessage.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('温度传感器列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    await loadSummary()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '温感器管理列表读取失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload) {
      throw new Error('温感器动作未生效，请稍后重试')
    }
    if (!payload.ok) {
      errorMessage.value = payload.message
    }
    if (payload.entry && detailRow.value?.id === payload.entry.id) {
      detailRow.value = payload.entry
    }
    await reload()
    // reload 会清空提示位，动作执行结果在列表刷新后重新显示
    if (payload.ok) {
      noticeMessage.value = payload.message
    } else {
      errorMessage.value = payload.message
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '温感器管理操作失败'
  }
}

function openDetail(row: Row) {
  detailRow.value = row
}

function openCalibration(row?: Row) {
  calibrationError.value = ''
  calibrationForm.传感器编号 = row ? String(row['传感器编号'] ?? '') : ''
  calibrationForm.校准日期 = ''
  calibrationForm.下次校准日 = ''
  calibrationForm.精度等级 = row ? String(row['精度等级'] ?? '') : ''
  calibrationForm.电池电量 = ''
  calibrationOpen.value = true
}

async function submitCalibration() {
  calibrationError.value = ''
  const values: Record<string, string> = { ...calibrationForm }
  if (values.电池电量) values.电池电量 = `${values.电池电量}%`
  try {
    const response = await request(CALIBRATION_ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload) {
      throw new Error('校准记录未保存，请稍后重试')
    }
    if (!payload.ok) {
      // 日期倒挂 / 精度不符等拦截原因，原样展示给操作人
      calibrationError.value = payload.message
      return
    }
    calibrationOpen.value = false
    await reload()
  } catch (error) {
    calibrationError.value = error instanceof Error ? error.message : '校准记录保存失败'
  }
}

function openCreate() {
  createError.value = ''
  for (const field of createFields) createForm[field] = ''
  createOpen.value = true
}

async function submitCreate() {
  createError.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload) {
      throw new Error('传感器登记失败，请稍后重试')
    }
    if (!payload.ok) {
      createError.value = payload.message
      return
    }
    createOpen.value = false
    await reload()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '传感器登记失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.cell-tip {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--muted);
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.row-due td { background: #fff7ed; }
.row-block td { background: #fef3f2; }
.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
  white-space: nowrap;
}
.badge-due { background: #fdba74; color: #7c2d12; }
.badge-offset { background: #fde68a; color: #854d0e; }
.badge-block { background: #fda29b; color: #7a271a; }
.badge-off { background: #e2e8f0; color: #475569; }
.badge-warn { background: #fde68a; color: #713f12; }
.badge-ok { background: #bbf7d0; color: #14532d; }
.verdict-note { font-size: 12px; color: var(--muted); margin-left: 6px; }
.stat-danger { color: #b42318; }
.stat-warn { color: #b45309; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 20;
}
.modal {
  background: #fff;
  border-radius: 10px;
  width: 560px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 64px);
  overflow: auto;
  padding: 18px 20px;
}
.modal-head { display: flex; justify-content: space-between; align-items: center; }
.modal-head h3 { margin: 0; font-size: 16px; }
.detail-grid {
  display: grid;
  grid-template-columns: 110px 1fr;
  gap: 8px 12px;
  margin: 14px 0 0;
  font-size: 13px;
}
.detail-grid dt { color: var(--muted); }
.detail-grid dd { margin: 0; }
.reason-cell { color: #b45309; }
.modal-form { display: flex; flex-direction: column; gap: 10px; margin-top: 14px; }
.modal-form label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.modal-form input, .modal-form select { padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
.form-hint { font-size: 12px; color: var(--muted); margin: 4px 0; }
.error-text { color: #b42318; }
.notice-text { color: #b45309; }
</style>
