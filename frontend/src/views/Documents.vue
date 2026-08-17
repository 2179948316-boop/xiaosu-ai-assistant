<template>
  <div class="documents-page">
    <!-- 顶部导航 -->
    <header class="page-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" @click="$router.push('/')" text>
          返回对话
        </el-button>
        <h1>文档管理</h1>
      </div>
      <div class="header-right">
        <el-select v-model="selectedKbId" placeholder="选择知识库" style="width: 240px">
          <el-option
            v-for="kb in knowledgeBases"
            :key="kb.id"
            :label="kb.name"
            :value="kb.id"
          >
            <span>{{ kb.name }}</span>
            <el-tag v-if="kb.org_name" size="small" type="success" style="float: right; margin-left: 4px">{{ kb.org_name }}</el-tag>
            <el-tag size="small" type="info" style="float: right">{{ kb.document_count }}</el-tag>
          </el-option>
        </el-select>
        <el-button type="primary" :icon="Plus" @click="showCreateKb = true">
          新建知识库
        </el-button>
      </div>
    </header>

    <!-- 上传区域 -->
    <div class="upload-section" v-if="selectedKbId">
      <el-upload
        ref="uploadRef"
        :auto-upload="false"
        :on-change="handleFileChange"
        :file-list="fileList"
        accept=".pdf,.docx,.html,.htm,.txt,.md,.markdown"
        multiple
        drag
        class="upload-dragger"
      >
        <el-icon :size="48"><UploadFilled /></el-icon>
        <div class="el-upload__text">
          拖拽文件到此处，或 <em>点击上传</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">
            支持 PDF、DOCX、HTML、TXT、Markdown 格式，单个文件不超过 50MB；同名文件重复上传将覆盖旧版本
          </div>
        </template>
      </el-upload>
      <el-button
        v-if="fileList.length > 0"
        type="primary"
        :loading="uploading"
        @click="handleUpload"
        style="margin-top: 12px"
      >
        {{ uploading ? `上传中 (${uploadProgress}%)` : `上传 ${fileList.length} 个文件` }}
      </el-button>
    </div>

    <!-- 文档列表 -->
    <div class="documents-list" v-if="selectedKbId">
      <!-- 批量操作栏 -->
      <div class="batch-bar" v-if="selectedDocIds.length > 0">
        <span class="batch-info">已选择 {{ selectedDocIds.length }} 项</span>
        <el-button type="danger" :icon="Delete" :loading="batchDeleting" @click="handleBatchDelete">
          批量删除
        </el-button>
      </div>

      <el-table
        ref="tableRef"
        :data="documents"
        stripe
        style="width: 100%"
        @selection-change="handleSelectionChange"
      >
        <el-table-column type="selection" width="40" />
        <el-table-column prop="filename" label="文件名" min-width="200" />
        <el-table-column prop="file_type" label="类型" width="80" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="getFileTypeColor(row.file_type)">
              {{ row.file_type?.toUpperCase() }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="100" align="center">
          <template #default="{ row }">
            {{ formatFileSize(row.file_size) }}
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="切片数" width="80" align="center" />
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="statusType(row.status)"
            >
              {{ statusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="上传时间" width="180" align="center">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ row }">
            <el-button
              type="danger"
              :icon="Delete"
              size="small"
              circle
              @click="handleDeleteDoc(row)"
            />
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 未选择知识库 -->
    <div v-if="!selectedKbId" class="empty-state">
      <el-empty description="请先选择或创建一个知识库" />
    </div>

    <!-- 创建知识库弹窗 -->
    <el-dialog v-model="showCreateKb" title="创建知识库" width="460px">
      <el-form :model="newKb" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="newKb.name" placeholder="输入知识库名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="newKb.description" type="textarea" :rows="3" placeholder="可选" />
        </el-form-item>
        <el-form-item label="所属空间">
          <el-select v-model="newKb.org_id" placeholder="个人空间（私有）" clearable style="width: 100%">
            <el-option label="个人空间（仅自己可见）" :value="null" />
            <el-option
              v-for="org in organizations"
              :key="org.id"
              :label="org.name"
              :value="org.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateKb = false">取消</el-button>
        <el-button type="primary" @click="handleCreateKb" :loading="creatingKb">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { ArrowLeft, Plus, Delete, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getKnowledgeBases, createKnowledgeBase,
  uploadDocument, getDocuments, deleteDocument, batchDeleteDocuments
} from '../api/document'
import { getOrganizations } from '../api/organization'

const knowledgeBases = ref([])
const organizations = ref([])
const selectedKbId = ref(null)
const documents = ref([])
const fileList = ref([])
const uploading = ref(false)
const uploadProgress = ref(0)
const showCreateKb = ref(false)
const creatingKb = ref(false)
const newKb = ref({ name: '', description: '', org_id: null })
const uploadRef = ref(null)
const tableRef = ref(null)
const selectedDocIds = ref([])
const batchDeleting = ref(false)

function handleSelectionChange(selection) {
  selectedDocIds.value = selection.map(s => s.id)
}

async function loadKnowledgeBases() {
  try {
    knowledgeBases.value = await getKnowledgeBases()
    if (knowledgeBases.value.length > 0 && !selectedKbId.value) {
      selectedKbId.value = knowledgeBases.value[0].id
    }
  } catch (e) {}
}

async function loadDocuments() {
  if (!selectedKbId.value) return
  try {
    documents.value = await getDocuments(selectedKbId.value)
  } catch (e) {
    documents.value = []
  }
}

function handleFileChange(file) {
  fileList.value.push(file)
}

async function handleUpload() {
  if (!selectedKbId.value || fileList.value.length === 0) return
  uploading.value = true
  uploadProgress.value = 0

  let successCount = 0
  let failCount = 0

  for (let i = 0; i < fileList.value.length; i++) {
    try {
      await uploadDocument(
        selectedKbId.value,
        fileList.value[i].raw,
        (progressEvent) => {
          if (progressEvent.total) {
            uploadProgress.value = Math.round((progressEvent.loaded / progressEvent.total) * 100)
          }
        }
      )
      successCount++
    } catch (e) {
      failCount++
    }
  }

  uploading.value = false
  fileList.value = []
  if (uploadRef.value) uploadRef.value.clearFiles()

  if (successCount > 0) {
    ElMessage.success(`成功上传 ${successCount} 个文件${failCount > 0 ? `，${failCount} 个失败` : ''}`)
    await Promise.all([loadDocuments(), loadKnowledgeBases()])
  }
}

async function handleDeleteDoc(doc) {
  try {
    await ElMessageBox.confirm(`确定删除文件 "${doc.filename}"？`, '提示', { type: 'warning' })
    await deleteDocument(doc.id)
    ElMessage.success('文档已删除')
    await Promise.all([loadDocuments(), loadKnowledgeBases()])
  } catch (e) {}
}

async function handleBatchDelete() {
  if (selectedDocIds.value.length === 0) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${selectedDocIds.value.length} 个文档？`,
      '批量删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    batchDeleting.value = true
    const res = await batchDeleteDocuments(selectedDocIds.value)
    ElMessage.success(res.message || `成功删除 ${selectedDocIds.value.length} 个文档`)
    selectedDocIds.value = []
    if (tableRef.value) tableRef.value.clearSelection()
    await Promise.all([loadDocuments(), loadKnowledgeBases()])
  } catch (e) {
    if (e?.code !== 'cancel') {
      ElMessage.error('批量删除失败')
    }
  } finally {
    batchDeleting.value = false
  }
}

async function handleCreateKb() {
  if (!newKb.value.name.trim()) {
    ElMessage.warning('请输入知识库名称')
    return
  }
  creatingKb.value = true
  try {
    const kb = await createKnowledgeBase({
      name: newKb.value.name,
      description: newKb.value.description,
      org_id: newKb.value.org_id,
    })
    knowledgeBases.value.unshift(kb)
    selectedKbId.value = kb.id
    showCreateKb.value = false
    newKb.value = { name: '', description: '', org_id: null }
    ElMessage.success('知识库创建成功')
  } catch (e) {} finally {
    creatingKb.value = false
  }
}

function formatFileSize(bytes) {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  const d = new Date(dateStr)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function statusType(status) {
  const map = { pending: 'info', processing: 'warning', completed: 'success', failed: 'danger' }
  return map[status] || 'info'
}

function statusText(status) {
  const map = { pending: '等待中', processing: '处理中', completed: '已完成', failed: '失败' }
  return map[status] || status
}

function getFileTypeColor(type) {
  const map = { pdf: 'danger', docx: 'primary', html: 'success', txt: 'info' }
  return map[type] || ''
}

watch(selectedKbId, () => {
  loadDocuments()
})

onMounted(async () => {
  await Promise.all([loadKnowledgeBases(), loadOrganizations()])
})

async function loadOrganizations() {
  try {
    organizations.value = await getOrganizations()
  } catch (e) {}
}
</script>

<style scoped>
.documents-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
  overflow: hidden;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  background: white;
  border-bottom: 1px solid #e4e7ed;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.header-left h1 {
  font-size: 20px;
  margin: 0;
  color: #303133;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.upload-section {
  padding: 24px;
  flex-shrink: 0;
}

.upload-dragger {
  max-width: 600px;
}

.documents-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 24px 24px;
}

.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.batch-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #fff7e6;
  border: 1px solid #ffe7a3;
  border-radius: 4px;
  margin-bottom: 12px;
}

.batch-info {
  font-size: 14px;
  color: #e6a23c;
}
</style>
