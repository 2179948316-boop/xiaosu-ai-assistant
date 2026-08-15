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
    <div
      v-for="(msg, index) in messages"
      :key="index"
      :class="['message', `message-${msg.role}`]"
    >
      <div class="message-avatar">
        <el-icon v-if="msg.role === 'user'" :size="20"><User /></el-icon>
        <el-icon v-else :size="20" color="#409eff"><Monitor /></el-icon>
      </div>
      <div class="message-body">
        <div class="message-role">{{ msg.role === 'user' ? '我' : 'AI 助手' }}</div>
        <div class="message-content" v-html="renderMarkdown(msg.content)"></div>
        <!-- 复制按钮 (仅助手消息) -->
        <div v-if="msg.role === 'assistant' && msg.content" class="message-actions">
          <el-button
            size="small"
            text
            :icon="CopyDocument"
            @click="handleCopy(msg.content)"
          >
            复制
          </el-button>
        </div>
        <!-- 来源引用 -->
        <div v-if="msg.sources && msg.sources.length > 0" class="message-sources">
          <el-divider content-position="left">参考来源</el-divider>
          <div v-for="(source, si) in msg.sources" :key="si" class="source-item">
            <el-icon><Document /></el-icon>
            <span class="source-name">{{ source.filename }}</span>
            <el-tag size="small" type="info">相关度 {{ (source.score * 100).toFixed(0) }}%</el-tag>
          </div>
        </div>
      </div>
    </div>

    <!-- 流式输出中的消息 -->
    <div v-if="isStreaming" class="message message-assistant">
      <div class="message-avatar">
        <el-icon :size="20" color="#409eff"><Monitor /></el-icon>
      </div>
      <div class="message-body">
        <div class="message-role">AI 助手</div>
        <!-- 来源引用 -->
        <div v-if="currentSources.length > 0" class="message-sources" style="margin-bottom: 8px">
          <div v-for="(source, si) in currentSources" :key="si" class="source-item">
            <el-icon><Document /></el-icon>
            <span class="source-name">{{ source.filename }}</span>
            <el-tag size="small" type="info">相关度 {{ (source.score * 100).toFixed(0) }}%</el-tag>
          </div>
        </div>
        <div class="message-content" v-html="renderMarkdown(streamingContent)">
        </div>
        <span class="typing-cursor">|</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import {
  User, Monitor, Document,
  ChatLineSquare, Files, Search, List, CopyDocument
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'

const props = defineProps({
  // 历史消息列表
  messages: { type: Array, default: () => [] },
  // 是否正在流式输出
  isStreaming: { type: Boolean, default: false },
  // 流式输出中的增量内容
  streamingContent: { type: String, default: '' },
  // 流式输出中的参考来源
  currentSources: { type: Array, default: () => [] },
})

defineEmits(['quick-question'])

const messagesContainer = ref(null)

// Markdown 渲染
function renderMarkdown(text) {
  if (!text) return ''
  try {
    return marked(text, { breaks: true, gfm: true })
  } catch {
    return text
  }
}

// 滚动到底部
function scrollToBottom() {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

// 消息或流式内容变化时自动滚动
watch(() => props.messages, scrollToBottom, { deep: true })
watch(() => props.streamingContent, scrollToBottom)

// 复制消息内容
async function handleCopy(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    // 降级方案
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

/* 欢迎页 */
.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #909399;
}

.welcome h2 {
  margin: 16px 0 8px;
  color: #303133;
}

.welcome p {
  margin-bottom: 32px;
}

.welcome-tips {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  justify-content: center;
}

.tip-card {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 20px;
  background: white;
  border-radius: 8px;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
  transition: all 0.2s;
  font-size: 14px;
  color: #606266;
}

.tip-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  transform: translateY(-2px);
}

/* 消息 */
.message {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
  max-width: 800px;
}

.message-user {
  flex-direction: row-reverse;
  margin-left: auto;
}

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.message-user .message-avatar {
  background: #409eff;
  color: white;
}

.message-assistant .message-avatar {
  background: #e8f4ff;
}

.message-body {
  max-width: calc(100% - 60px);
}

.message-role {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
}

.message-user .message-role {
  text-align: right;
}

.message-content {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}

.message-user .message-content {
  background: #409eff;
  color: white;
  border-top-right-radius: 4px;
}

.message-assistant .message-content {
  background: white;
  color: #303133;
  border-top-left-radius: 4px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
}

.typing-cursor {
  animation: blink 1s infinite;
  color: #409eff;
  font-weight: bold;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

/* 来源引用 */
.message-sources {
  margin-top: 8px;
}

.source-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: #f0f9ff;
  border-radius: 4px;
  font-size: 12px;
  margin: 2px 4px 2px 0;
  color: #606266;
}

.source-name {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 消息操作按钮 */
.message-actions {
  margin-top: 4px;
}

.message-actions .el-button {
  color: #909399 !important;
  font-size: 12px;
  padding: 2px 6px;
}

.message-actions .el-button:hover {
  color: #409eff !important;
}

@media (max-width: 768px) {
  .messages-container {
    padding: 16px;
  }

  .message {
    max-width: 100%;
  }

  .welcome-tips {
    flex-direction: column;
    padding: 0 16px;
  }

  .tip-card {
    width: 100%;
    justify-content: center;
  }
}
</style>
