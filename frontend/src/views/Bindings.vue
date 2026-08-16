<template>
  <div class="bindings-page">
    <!-- 顶部导航 -->
    <header class="page-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" @click="$router.push('/')" text>
          返回对话
        </el-button>
        <h1>知识库绑定</h1>
        <el-tag size="small" type="warning" class="admin-tag">管理员</el-tag>
      </div>
      <div class="header-right">
        <el-button :icon="DataBoard" @click="$router.push('/admin/logs')">
          对话日志
        </el-button>
        <el-button :icon="Setting" @click="$router.push('/settings')">
          系统设置
        </el-button>
      </div>
    </header>

    <!-- 规则说明 -->
    <el-alert
      type="info"
      :closable="false"
      show-icon
      class="rule-alert"
      title="机器人检索知识库的优先级：群绑定(chat_id) > 个人绑定(open_id) > 全局默认知识库 > 第一个知识库。"
    />

    <!-- 新增绑定 -->
    <el-card shadow="never" class="create-card">
      <template #header>
        <span class="card-title">新增 / 更新绑定</span>
      </template>
      <el-form :inline="true" :model="form" @submit.prevent>
        <el-form-item label="绑定对象">
          <el-radio-group v-model="form.scopeType">
            <el-radio value="chat">按群（chat_id）</el-radio>
            <el-radio value="open">按人（open_id）</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="form.scopeType === 'chat' ? '群 chat_id' : '用户 open_id'">
          <el-input
            v-model="form.scopeValue"
            :placeholder="form.scopeType === 'chat' ? '如 oc_xxxxxxxxxx' : '如 ou_xxxxxxxxxx'"
            clearable
            style="width: 240px"
          />
        </el-form-item>
        <el-form-item label="绑定知识库">
          <el-select
            v-model="form.kbId"
            placeholder="选择知识库"
            style="width: 220px"
            filterable
          >
            <el-option
              v-for="kb in knowledgeBases"
              :key="kb.id"
              :label="`${kb.name}（${kb.document_count} 篇）`"
              :value="kb.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :icon="Plus" :loading="submitting" @click="handleCreate">
            保存绑定
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 绑定列表 -->
    <el-table :data="bindings" stripe style="width: 100%" v-loading="loading">
      <el-table-column prop="id" label="ID" width="70" align="center" />
      <el-table-column prop="scope_label" label="绑定对象" min-width="220" show-overflow-tooltip />
      <el-table-column label="知识库" min-width="160">
        <template #default="{ row }">
          <el-tag v-if="row.kb_name" size="small" type="primary" effect="plain">
            {{ row.kb_name }}
          </el-tag>
          <span v-else class="muted">已删除</span>
        </template>
      </el-table-column>
      <el-table-column label="文档数" width="90" align="center">
        <template #default="{ row }">
          {{ row.document_count ?? '-' }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="170" align="center">
        <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="更新时间" width="170" align="center">
        <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" align="center">
        <template #default="{ row }">
          <el-button type="danger" size="small" :icon="Delete" @click="handleDelete(row)">
            解除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && bindings.length === 0" description="暂无绑定，可在上方新增" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ArrowLeft, Setting, DataBoard, Plus, Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getAdminBindings, createAdminBinding, deleteAdminBinding } from '../api/admin'
import { getKnowledgeBases } from '../api/document'

const bindings = ref([])
const knowledgeBases = ref([])
const loading = ref(false)
const submitting = ref(false)

// 新增表单：按群(chat) 或 按人(open)
const form = ref({ scopeType: 'chat', scopeValue: '', kbId: null })

async function loadBindings() {
  loading.value = true
  try {
    bindings.value = await getAdminBindings()
  } catch (e) {
    // 拦截器已提示
  } finally {
    loading.value = false
  }
}

async function loadKnowledgeBases() {
  try {
    knowledgeBases.value = await getKnowledgeBases()
  } catch (e) {
    // 拦截器已提示
  }
}

async function handleCreate() {
  if (!form.value.scopeValue.trim()) {
    ElMessage.warning(form.value.scopeType === 'chat' ? '请输入群 chat_id' : '请输入用户 open_id')
    return
  }
  if (!form.value.kbId) {
    ElMessage.warning('请选择要绑定的知识库')
    return
  }
  submitting.value = true
  try {
    const payload = { kb_id: form.value.kbId }
    if (form.value.scopeType === 'chat') payload.chat_id = form.value.scopeValue.trim()
    else payload.open_id = form.value.scopeValue.trim()
    await createAdminBinding(payload)
    ElMessage.success('绑定已保存')
    form.value.scopeValue = ''
    form.value.kbId = null
    await loadBindings()
  } catch (e) {
    // 拦截器已提示
  } finally {
    submitting.value = false
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定解除「${row.scope_label}」的知识库绑定吗？解除后机器人将回退到默认知识库。`,
      '解除绑定',
      { type: 'warning', confirmButtonText: '解除', cancelButtonText: '取消' },
    )
  } catch (e) {
    return // 用户取消
  }
  try {
    await deleteAdminBinding(row.id)
    ElMessage.success('已解除绑定')
    await loadBindings()
  } catch (e) {
    // 拦截器已提示
  }
}

function formatDate(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 19)
}

onMounted(() => {
  loadBindings()
  loadKnowledgeBases()
})
</script>

<style scoped>
.bindings-page {
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

.rule-alert {
  margin-bottom: 16px;
}

.create-card {
  margin-bottom: 16px;
}

.card-title {
  font-weight: 600;
  color: #303133;
}

.muted {
  color: #c0c4cc;
  font-size: 13px;
}
</style>
