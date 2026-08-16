<template>
  <div class="admin-logs-page">
    <!-- 顶部导航 -->
    <header class="page-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" @click="$router.push('/')" text>
          返回对话
        </el-button>
        <h1>对话日志</h1>
        <el-tag size="small" type="warning" class="admin-tag">管理员</el-tag>
      </div>
      <div class="header-right">
        <el-button :icon="Setting" @click="$router.push('/settings')">
          系统设置
        </el-button>
      </div>
    </header>

    <!-- 筛选区 -->
    <div class="filter-bar">
      <el-input
        v-model="filters.username"
        placeholder="按用户名筛选"
        clearable
        style="width: 180px"
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      />
      <el-date-picker
        v-model="filters.dateRange"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        value-format="YYYY-MM-DD"
        style="width: 280px"
        @change="handleSearch"
      />
      <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
      <el-button :icon="Refresh" @click="handleReset">重置</el-button>
    </div>

    <!-- 日志表格 -->
    <el-table :data="logs" stripe style="width: 100%" @expand-change="handleExpand">
      <el-table-column type="expand" width="40">
        <template #default="{ row }">
          <div v-if="detailLoading === row.id" class="detail-loading">加载消息详情…</div>
          <div v-else-if="row._detail" class="detail-panel">
            <div class="detail-meta">
              来源：<el-tag size="small" :type="row.source === 'im' ? 'success' : 'info'">
                {{ row.source === 'im' ? '飞书 IM' : 'Web' }}
              </el-tag>
              <span v-if="row._detail.conversation.open_id" class="meta-item">
                open_id: {{ row._detail.conversation.open_id }}
              </span>
              <span v-if="row._detail.conversation.chat_id" class="meta-item">
                chat_id: {{ row._detail.conversation.chat_id }}
              </span>
            </div>
            <div
              v-for="msg in row._detail.messages"
              :key="msg.id"
              :class="['msg-item', `msg-${msg.role}`]"
            >
              <div class="msg-head">
                <el-tag size="small" :type="msg.role === 'user' ? 'primary' : 'success'" effect="plain">
                  {{ msg.role === 'user' ? '用户' : '小苏' }}
                </el-tag>
                <span class="msg-time">{{ formatDate(msg.created_at) }}</span>
                <span v-if="msg.token_count" class="msg-tokens">
                  {{ msg.token_count }} tokens
                </span>
              </div>
              <div class="msg-content">{{ msg.content }}</div>
              <!-- 工具调用轨迹 -->
              <div v-if="msg.tool_calls && msg.tool_calls.length" class="msg-tools">
                <div v-for="(tc, i) in msg.tool_calls" :key="i" class="tool-chip">
                  <el-icon><Cpu /></el-icon>
                  {{ tc.name }}
                  <span class="tool-args">{{ JSON.stringify(tc.arguments) }}</span>
                </div>
              </div>
              <!-- 引用来源 -->
              <div v-if="msg.sources && msg.sources.length" class="msg-sources">
                <div v-for="(s, i) in msg.sources" :key="i" class="source-item">
                  📎 {{ s.filename }}
                  <el-tag size="small" type="warning" effect="plain">
                    {{ (s.score * 100).toFixed(0) }}%
                  </el-tag>
                  <span class="source-preview">{{ s.text_preview }}</span>
                </div>
              </div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="title" label="对话标题" min-width="180" show-overflow-tooltip />
      <el-table-column prop="username" label="用户" width="150" show-overflow-tooltip />
      <el-table-column label="来源" width="90" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="row.source === 'im' ? 'success' : 'info'" effect="light">
            {{ row.source === 'im' ? '飞书' : 'Web' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="message_count" label="消息数" width="80" align="center" />
      <el-table-column prop="tool_call_count" label="工具调用" width="90" align="center">
        <template #default="{ row }">
          <span v-if="row.tool_call_count > 0" class="tool-count">{{ row.tool_call_count }}</span>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="total_tokens" label="Tokens" width="100" align="center">
        <template #default="{ row }">
          {{ row.total_tokens > 0 ? row.total_tokens : '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="last_answer" label="最近回答" min-width="220" show-overflow-tooltip />
      <el-table-column label="更新时间" width="170" align="center">
        <template #default="{ row }">
          {{ formatDate(row.updated_at) }}
        </template>
      </el-table-column>
    </el-table>

    <!-- 空状态 -->
    <el-empty v-if="!loading && logs.length === 0" description="暂无对话记录" />

    <!-- 分页 -->
    <div class="pagination-wrap" v-if="total > 0">
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :total="total"
        layout="total, prev, pager, next"
        @current-change="loadLogs"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ArrowLeft, Setting, Search, Refresh, Cpu } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getAdminLogs, getAdminLogDetail } from '../api/admin'

const logs = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const detailLoading = ref(null)
const filters = reactive({ username: '', dateRange: null })

async function loadLogs() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize }
    if (filters.username) params.username = filters.username
    if (filters.dateRange && filters.dateRange.length === 2) {
      params.start = filters.dateRange[0]
      params.end = filters.dateRange[1]
    }
    const res = await getAdminLogs(params)
    logs.value = res.items
    total.value = res.total
  } catch (e) {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  page.value = 1
  loadLogs()
}

function handleReset() {
  filters.username = ''
  filters.dateRange = null
  page.value = 1
  loadLogs()
}

// 展开行 → 拉取完整消息（含 tool_calls / token_count / sources）
async function handleExpand(row, expandedRows) {
  const expanded = expandedRows.some(r => r.id === row.id)
  if (!expanded) return
  if (row._detail) return
  detailLoading.value = row.id
  try {
    row._detail = await getAdminLogDetail(row.id)
  } catch (e) {
  } finally {
    detailLoading.value = null
  }
}

function formatDate(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 19)
}

onMounted(loadLogs)
</script>

<style scoped>
.admin-logs-page {
  padding: 20px;
  height: 100%;
  overflow-y: auto;
  background: #f5f7fa;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-left h1 {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.filter-bar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
}

.detail-panel {
  padding: 8px 16px 16px 24px;
}

.detail-meta {
  display: flex;
  gap: 16px;
  align-items: center;
  margin-bottom: 10px;
  font-size: 12px;
  color: #909399;
}

.msg-item {
  border-left: 3px solid #dcdfe6;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: #fff;
  border-radius: 6px;
}

.msg-user {
  border-left-color: #409eff;
}

.msg-assistant {
  border-left-color: #67c23a;
}

.msg-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
}

.msg-time,
.msg-tokens {
  font-size: 12px;
  color: #909399;
}

.msg-content {
  font-size: 14px;
  color: #303133;
  white-space: pre-wrap;
  line-height: 1.6;
}

.msg-tools {
  margin-top: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tool-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #f0f2f5;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 12px;
  color: #606266;
}

.tool-args {
  color: #909399;
}

.msg-sources {
  margin-top: 8px;
}

.source-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #606266;
  margin-bottom: 4px;
}

.source-preview {
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 400px;
}

.tool-count {
  color: #e6a23c;
  font-weight: 600;
}

.muted {
  color: #c0c4cc;
}

.detail-loading {
  padding: 20px;
  color: #909399;
  font-size: 13px;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
