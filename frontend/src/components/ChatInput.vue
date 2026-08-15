<template>
  <div class="input-area">
    <div class="input-wrapper">
      <el-input
        v-model="inputMessage"
        type="textarea"
        :rows="1"
        :autosize="{ minRows: 1, maxRows: 5 }"
        placeholder="输入您的问题... (Enter 发送, Shift+Enter 换行)"
        @keydown="handleKeyDown"
        :disabled="isStreaming"
        resize="none"
      />
      <!-- 流式输出时显示停止按钮 -->
      <el-button
        v-if="isStreaming"
        type="danger"
        :icon="CloseBold"
        @click="$emit('stop')"
        circle
      />
      <!-- 非流式时显示发送按钮 -->
      <el-button
        v-else
        type="primary"
        :icon="Promotion"
        :disabled="!inputMessage.trim() || !kbSelected"
        @click="handleSend"
        circle
      />
    </div>
    <div class="input-hint">
      <span v-if="!kbSelected" class="hint-warning">请先选择一个知识库</span>
      <span v-else class="hint-info">当前知识库: {{ kbName }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Promotion, CloseBold } from '@element-plus/icons-vue'

defineProps({
  // 是否正在流式输出（禁用输入、切换停止按钮）
  isStreaming: { type: Boolean, default: false },
  // 是否已选择知识库
  kbSelected: { type: Boolean, default: false },
  // 当前知识库名称（用于底部提示）
  kbName: { type: String, default: '' },
})

const emit = defineEmits(['send', 'stop'])

const inputMessage = ref('')

function handleSend() {
  const message = inputMessage.value.trim()
  if (!message) return
  inputMessage.value = ''
  emit('send', message)
}

function handleKeyDown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}
</script>

<style scoped>
.input-area {
  padding: 16px 24px;
  background: white;
  border-top: 1px solid #e4e7ed;
}

.input-wrapper {
  display: flex;
  align-items: flex-end;
  gap: 12px;
}

.input-wrapper :deep(.el-textarea__inner) {
  border-radius: 12px;
  padding: 10px 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.input-hint {
  margin-top: 6px;
  font-size: 12px;
  padding-left: 4px;
}

.hint-warning {
  color: #e6a23c;
}

.hint-info {
  color: #909399;
}

@media (max-width: 768px) {
  .input-area {
    padding: 12px 16px;
  }
}
</style>
