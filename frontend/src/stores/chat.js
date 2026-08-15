import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useChatStore = defineStore('chat', () => {
  // 当前对话
  const currentConversationId = ref(null)
  const currentKbId = ref(null)

  // 消息列表
  const messages = ref([])

  // 流式状态
  const isStreaming = ref(false)
  const streamingContent = ref('')
  const currentSources = ref([])

  // 对话列表
  const conversations = ref([])

  function addMessage(msg) {
    messages.value.push(msg)
  }

  function setMessages(msgs) {
    messages.value = msgs
  }

  function clearStreaming() {
    streamingContent.value = ''
    currentSources.value = []
  }

  function appendStreamToken(token) {
    streamingContent.value += token
  }

  function setSources(sources) {
    currentSources.value = sources
  }

  function finishStreaming() {
    if (streamingContent.value) {
      messages.value.push({
        role: 'assistant',
        content: streamingContent.value,
        sources: currentSources.value,
        created_at: new Date().toISOString(),
      })
    }
    streamingContent.value = ''
    currentSources.value = []
    isStreaming.value = false
  }

  function resetChat() {
    messages.value = []
    currentConversationId.value = null
    clearStreaming()
  }

  return {
    currentConversationId,
    currentKbId,
    messages,
    isStreaming,
    streamingContent,
    currentSources,
    conversations,
    addMessage,
    setMessages,
    clearStreaming,
    appendStreamToken,
    setSources,
    finishStreaming,
    resetChat,
  }
})
