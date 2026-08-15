<template>
  <div class="chat-layout">
    <!-- 移动端菜单按钮 -->
    <div class="mobile-header" v-if="isMobile">
      <el-button :icon="Fold" text @click="sidebarVisible = !sidebarVisible" />
      <span class="mobile-title">知识库问答</span>
    </div>

    <!-- 移动端侧边栏遮罩 -->
    <div
      v-if="isMobile && sidebarVisible"
      class="sidebar-overlay"
      @click="sidebarVisible = false"
    />

    <!-- 侧边栏 -->
    <ChatSidebar
      ref="sidebarRef"
      :is-mobile="isMobile"
      :visible="sidebarVisible"
      :current-conv-id="currentConvId"
      @kb-change="handleKbChange"
      @new-chat="handleNewChat"
      @select-conversation="handleSelectConversation"
      @conversation-deleted="handleConversationDeleted"
    />

    <!-- 聊天主区域 -->
    <main class="chat-main">
      <MessageList
        :messages="messages"
        :is-streaming="isStreaming"
        :streaming-content="streamingContent"
        :current-sources="currentSources"
        :current-tools="currentTools"
        @quick-question="sendMessage"
      />
      <ChatInput
        :is-streaming="isStreaming"
        :kb-selected="!!selectedKb"
        :kb-name="selectedKb ? selectedKb.name : ''"
        @send="sendMessage"
        @stop="handleStopGenerate"
      />
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { Fold } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useChatStore } from '../stores/chat'
import { getMessages, chatStream } from '../api/chat'
import ChatSidebar from '../components/ChatSidebar.vue'
import MessageList from '../components/MessageList.vue'
import ChatInput from '../components/ChatInput.vue'

const chatStore = useChatStore()

// 状态
const sidebarRef = ref(null)
const selectedKb = ref(null)
const currentConvId = ref(null)
const isStreaming = ref(false)
const streamingContent = ref('')
const currentSources = ref([])
const currentTools = ref([])
const isMobile = ref(false)
const sidebarVisible = ref(false)
let abortStream = null

const messages = computed(() => chatStore.messages)

// 侧边栏同步当前选中的知识库
function handleKbChange(kb) {
  selectedKb.value = kb
}

// 新建对话
function handleNewChat() {
  // 中断正在进行的流式请求
  if (abortStream) {
    abortStream()
    abortStream = null
  }
  // 重置本地流式状态
  isStreaming.value = false
  streamingContent.value = ''
  currentSources.value = []
  currentTools.value = []
  // 重置对话状态
  chatStore.resetChat()
  currentConvId.value = null
}

// 选择对话
async function handleSelectConversation(conv) {
  // 中断正在进行的流式请求
  if (abortStream) {
    abortStream()
    abortStream = null
  }
  isStreaming.value = false
  streamingContent.value = ''
  currentSources.value = []
  currentTools.value = []

  currentConvId.value = conv.id
  chatStore.currentConversationId = conv.id
  if (isMobile.value) sidebarVisible.value = false
  try {
    const msgs = await getMessages(conv.id)
    chatStore.setMessages(msgs)
  } catch (e) {}
}

// 对话被删除：若为当前对话则重置
function handleConversationDeleted(convId) {
  if (currentConvId.value === convId) {
    chatStore.resetChat()
    currentConvId.value = null
  }
}

// 发送消息（含流式响应）
async function sendMessage(message) {
  if (!message || !selectedKb.value || isStreaming.value) return

  // 添加用户消息到界面
  chatStore.addMessage({
    role: 'user',
    content: message,
    created_at: new Date().toISOString(),
  })

  // 开始流式响应
  isStreaming.value = true
  streamingContent.value = ''
  currentSources.value = []
  currentTools.value = []

  abortStream = chatStream(
    {
      conversation_id: currentConvId.value,
      kb_id: selectedKb.value.id,
      message,
    },
    {
      onConversationId: (convId) => {
        currentConvId.value = convId
        chatStore.currentConversationId = convId
        // 乐观更新：立即将新对话加入侧边栏列表（不等后端 commit 完成）
        sidebarRef.value?.addConversation({
          id: convId,
          title: message.slice(0, 50),
          kb_id: selectedKb.value.id,
          updated_at: new Date().toISOString(),
        })
        // 延迟刷新确保与后端同步
        setTimeout(() => sidebarRef.value?.refreshConversations(), 500)
      },
      onChunk: (token) => {
        streamingContent.value += token
      },
      onSources: (sources) => {
        currentSources.value = sources
      },
      onTool: (tool) => {
        currentTools.value.push(tool)
      },
      onDone: () => {
        if (streamingContent.value) {
          chatStore.addMessage({
            role: 'assistant',
            content: streamingContent.value,
            sources: currentSources.value,
            tools: currentTools.value,
            created_at: new Date().toISOString(),
          })
        }
        streamingContent.value = ''
        currentSources.value = []
        currentTools.value = []
        isStreaming.value = false
      },
      onError: (err) => {
        ElMessage.error(err || '生成回复失败')
        isStreaming.value = false
        currentTools.value = []
      },
    }
  )
}

// 停止生成
function handleStopGenerate() {
  if (abortStream) {
    abortStream()
    abortStream = null
  }
  // 如果已有部分内容，保留为一条消息
  if (streamingContent.value) {
    chatStore.addMessage({
      role: 'assistant',
      content: streamingContent.value + '\n\n*(已停止生成)*',
      sources: currentSources.value,
      tools: currentTools.value,
      created_at: new Date().toISOString(),
    })
  }
  streamingContent.value = ''
  currentSources.value = []
  currentTools.value = []
  isStreaming.value = false
}

// 移动端检测
function checkMobile() {
  isMobile.value = window.innerWidth < 768
  if (!isMobile.value) {
    sidebarVisible.value = false
  }
}

onMounted(() => {
  checkMobile()
  window.addEventListener('resize', checkMobile)
})

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ===== 聊天主区域 ===== */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
  min-width: 0;
}

/* ===== 移动端头部 ===== */
.mobile-header {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 52px;
  background: #1a1a2e;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  z-index: 100;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.mobile-title {
  color: #fff;
  font-size: 16px;
  font-weight: 600;
}

.mobile-header .el-button {
  color: #fff !important;
}

/* 侧边栏遮罩 */
.sidebar-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 199;
}

/* ===== 响应式适配 ===== */
@media (max-width: 768px) {
  .chat-layout {
    flex-direction: column;
    padding-top: 52px;
  }

  .chat-main {
    width: 100%;
    height: calc(100vh - 52px);
  }
}
</style>
