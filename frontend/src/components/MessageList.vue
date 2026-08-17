<template>
  <div class="messages-container" ref="messagesContainer">
    <!-- 欢迎页面 -->
    <div v-if="messages.length === 0 && !isStreaming" class="welcome">
      <el-icon :size="64" color="#c0c4cc"><ChatLineSquare /></el-icon>
      <h2>欢迎使用知识库问答系统</h2>
      <p>选择一个知识库，然后输入您的问题</p>
      <div class="welcome-tips">
        <div class="tip-card" @click="$emit('quick-question', '请帮我总结知识库中的主要内容')">
          <el-icon><Files /></el-icon>
          <span>总结知识库主要内容</span>
        </div>
        <div class="tip-card" @click="$emit('quick-question', '知识库中有哪些关键概念和定义？')">
          <el-icon><Search /></el-icon>
          <span>查找关键概念和定义</span>
        </div>
        <div class="tip-card" @click="$emit('quick-question', '请列出知识库中提到的重要流程和规范')">
          <el-icon><List /></el-icon>
          <span>查找重要流程和规范</span>
        </div>
      </div>
    </div>

    <!-- 消息列表 -->
    <div v-for="(msg, index) in messages" :key="index" :class="['message', `message-${msg.role}`]">
      <div class="message-avatar">
        <el-icon v-if="msg.role === 'user'" :size="20"><User /></el-icon>
        <el-icon v-else :size="20" color="#409eff"><Monitor /></el-icon>
      </div>
      <div class="message-body">
        <div class="message-role">{{ msg.role === 'user' ? '我' : 'AI 助手' }}</div>
        <!-- 工具调用轨迹 -->
        <div v-if="msg.tools && msg.tools.length > 0" class="message-tools">
          <span v-for="(tool, ti) in msg.tools" :key="ti" class="tool-item">
            <el-icon><Tools /></el-icon>
            <span>{{ toolLabel(tool.name) }}</span>
            <span v-if="toolArgsText(tool)" class="tool-args">{{ toolArgsText(tool) }}</span>
          </span>
        </div>
        <div class="message-content" v-html="renderMarkdown(msg.content)"></div>
        <!-- 复制按钮 -->
        <div v-if="msg.role === 'assistant' && msg.content" class="message-actions">
          <el-button size="small" text :icon="CopyDocument" @click="handleCopy(msg.content)">复制</el-button>
        </div>
        <!-- 来源引用 -->
        <div v-if="msg.sources && msg.sources.length > 0" class="message-sources">
          <el-divider content-position="left">参考来源</el-divider>
          <div v-for="(source, si) in msg.sources" :key="si" class="source-item source-clickable" title="点击查看原文" @click="openDocumentPreview(source)">
            <el-icon><Document /></el-icon>
            <span class="source-name">{{ source.filename }}</span>
            <el-tag size="small" type="info">相关度 {{ (source.score * 100).toFixed(0) }}%</el-tag>
          </div>
        </div>
      </div>
    </div>

    <!-- 流式输出消息 -->
    <div v-if="isStreaming" class="message message-assistant">
      <div class="message-avatar"><el-icon :size="20" color="#409eff"><Monitor /></el-icon></div>
      <div class="message-body">
        <div class="message-role">AI 助手</div>
        <div v-if="currentTools.length > 0" class="message-tools">
          <span v-for="(tool, ti) in currentTools" :key="ti" class="tool-item">
            <el-icon><Tools /></el-icon>
            <span>{{ toolLabel(tool.name) }}</span>
            <span v-if="toolArgsText(tool)" class="tool-args">{{ toolArgsText(tool) }}</span>
          </span>
        </div>
        <div v-if="currentSources.length > 0" class="message-sources" style="margin-bottom: 8px">
          <div v-for="(source, si) in currentSources" :key="si" class="source-item source-clickable" title="点击查看原文" @click="openDocumentPreview(source)">
            <el-icon><Document /></el-icon>
            <span class="source-name">{{ source.filename }}</span>
            <el-tag size="small" type="info">相关度 {{ (source.score * 100).toFixed(0) }}%</el-tag>
          </div>
        </div>
        <div class="message-content" v-html="renderMarkdown(streamingContent)"></div>
        <span class="typing-cursor">|</span>
      </div>
    </div>

    <!-- 文档全文预览弹窗 -->
    <el-dialog v-model="previewVisible" :title="previewFilename" fullscreen>
      <div v-if="previewLoading" class="preview-loading">加载中…</div>
      <div v-else-if="previewError" class="preview-error">{{ previewError }}</div>
      <div v-else ref="previewContent" class="preview-content">
        <div
          v-for="(seg, idx) in previewSegments"
          :key="idx"
          :ref="el => setChunkRef(el, idx)"
          :class="['preview-chunk', { 'preview-chunk-active': idx === activeChunkIndex }]"
          @click="activeChunkIndex = idx"
        >
          <div class="preview-chunk-label">第 {{ idx + 1 }} 段</div>
          <div class="preview-chunk-text">{{ seg }}</div>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import {
  User, Monitor, Document, Tools,
  ChatLineSquare, Files, Search, List, CopyDocument
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'
import { getDocumentPreview } from '../api/document'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  isStreaming: { type: Boolean, default: false },
  streamingContent: { type: String, default: '' },
  currentSources: { type: Array, default: () => [] },
  currentTools: { type: Array, default: () => [] },
})

defineEmits(['quick-question'])

const messagesContainer = ref(null)

const TOOL_LABELS = {
  get_employee_info: '查询员工信息',
  get_attendance: '查询考勤记录',
  get_orders: '查询订单记录',
  get_current_time: '获取当前时间',
  search_kb: '检索知识库',
}

function toolLabel(name) {
  return TOOL_LABELS[name] || name
}

function toolArgsText(tool) {
  const args = tool.arguments || {}
  const parts = []
  if (args.emp_id != null) parts.push(`员工 ${args.emp_id}`)
  if (args.query) parts.push(`「${args.query}」`)
  if (args.start_date) parts.push(`${args.start_date} ~ ${args.end_date || '至今'}`)
  return parts.join(' · ')
}

// ============ 文档全文预览 ============
const previewVisible = ref(false)
const previewLoading = ref(false)
const previewError = ref('')
const previewFilename = ref('')
const previewSegments = ref([])
const activeChunkIndex = ref(-1)
const previewContent = ref(null)
const chunkRefs = ref({})

function setChunkRef(el, idx) {
  if (el) chunkRefs.value[idx] = el
}

async function openDocumentPreview(source) {
  previewVisible.value = true
  previewLoading.value = true
  previewError.value = ''
  previewSegments.value = []
  activeChunkIndex.value = -1
  previewFilename.value = source.filename || '文档预览'

  // 从 source 提取 doc_id（chunk_id 形如 "doc{id}_chunk{idx}"）
  const chunkId = source.chunk_id || ''
  const docIdMatch = chunkId.match(/doc(\d+)/)
  const docId = docIdMatch ? parseInt(docIdMatch[1]) : null
  if (!docId) {
    // 无 docId 时回退旧弹窗：直接显示 text_preview
    previewLoading.value = false
    previewSegments.value = [source.text_preview || '（无原文片段）']
    return
  }

  try {
    const data = await getDocumentPreview(docId)
    if (!data.chunks || data.chunks.length === 0) {
      // 有全文但无 chunk 数据
      previewSegments.value = [data.full_text.substring(0, 3000)] // 截断避免撑爆
    } else {
      // 按 chunk_index 排序，用 full_text 或 chunk text 填充
      previewSegments.value = data.chunks.map(c => c.text)
      // 匹配当前 chunk
      const targetIdx = source.chunk_index
      if (targetIdx >= 0 && targetIdx < data.chunks.length) {
        activeChunkIndex.value = targetIdx
        // 延迟滚动到高亮位置
        nextTick(() => scrollToChunk(targetIdx))
      }
    }
  } catch (e) {
    previewError.value = '加载文档失败：' + (e.message || '未知错误')
  } finally {
    previewLoading.value = false
  }
}

function scrollToChunk(idx) {
  const el = chunkRefs.value[idx]
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}

// ============ Markdown 渲染 ============
function renderMarkdown(text) {
  if (!text) return ''
  try {
    return marked(text, { breaks: true, gfm: true })
  } catch {
    return text
  }
}

// ============ 滚动 ============
function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

watch(() => props.messages, scrollToBottom, { deep: true })
watch(() => props.streamingContent, scrollToBottom)

// ============ 复制 ============
async function handleCopy(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.style.position = 'fixed'
    textarea.style.opacity = '0'
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    ElMessage.success('已复制到剪贴板')
  }
}
</script>

<style scoped>
.messages-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #909399;
}
.welcome h2 { margin: 16px 0 8px; color: #303133; }
.welcome p { margin-bottom: 32px; }
.welcome-tips { display: flex; gap: 16px; flex-wrap: wrap; justify-content: center; }

.tip-card { display: flex; align-items: center; gap: 8px; padding: 12px 20px; background: white; border-radius: 8px; cursor: pointer; box-shadow: 0 2px 8px rgba(0,0,0,0.06); transition: all 0.2s; font-size: 14px; color: #606266; }
.tip-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.12); transform: translateY(-2px); }

.message { display: flex; gap: 12px; margin-bottom: 24px; max-width: 800px; }
.message-user { flex-direction: row-reverse; margin-left: auto; }
.message-avatar { width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.message-user .message-avatar { background: #409eff; color: white; }
.message-assistant .message-avatar { background: #e8f4ff; }
.message-body { max-width: calc(100% - 60px); }
.message-role { font-size: 12px; color: #909399; margin-bottom: 4px; }
.message-content { padding: 12px 16px; border-radius: 12px; font-size: 14px; line-height: 1.6; word-break: break-word; }
.message-user .message-content { background: #409eff; color: white; border-top-right-radius: 4px; }
.message-assistant .message-content { background: white; color: #303133; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }

.typing-cursor { animation: blink 1s infinite; color: #409eff; font-weight: bold; }
@keyframes blink { 0%,50% { opacity: 1; } 51%,100% { opacity: 0; } }

.message-tools { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.tool-item { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; background: #f5f3ff; border: 1px solid #e4e0f7; border-radius: 14px; font-size: 12px; color: #6b5db8; }
.tool-args { color: #a09bc8; font-size: 11px; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.message-sources { margin-top: 8px; }
.source-item { display: inline-flex; align-items: center; gap: 4px; padding: 4px 10px; background: #f0f9ff; border-radius: 4px; font-size: 12px; margin: 2px 4px 2px 0; color: #606266; }
.source-name { max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.source-clickable { cursor: pointer; transition: all 0.2s; }
.source-clickable:hover { background: #d9edff; box-shadow: 01px 4px rgba(64,158,255,0.2); }

/* 文档预览 */
.preview-content { max-height: 70vh; overflow-y: auto; }
.preview-chunk { padding: 12px 16px; margin-bottom: 8px; border-left: 3px solid #e4e7ed; border-radius: 4px; cursor: pointer; transition: all 0.2s; }
.preview-chunk:hover { background: #fafafa; }
.preview-chunk-active { background: #fff8e1; border-left-color: #ff9800; }
.preview-chunk-label { font-size: 11px; color: #c0c4cc; margin-bottom: 4px; }
.preview-chunk-text { font-size: 14px; line-height: 1.8; white-space: pre-wrap; word-break: break-word; color: #303133; }
.preview-loading,.preview-error { padding: 40px; text-align: center; color: #909399; }

.message-actions { margin-top: 4px; }
.message-actions .el-button { color: #909399 !important; font-size: 12px; padding: 2px 6px; }

@media (max-width: 768px) {
  .messages-container { padding: 16px; }
  .message { max-width: 100%; }
  .welcome-tips { flex-direction: column; padding: 0 16px; }
  .tip-card { width: 100%; justify-content: center; }
}
</style>