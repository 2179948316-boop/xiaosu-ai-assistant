import api from './index'

// 对话管理
export const getConversations = () => api.get('/conversations')
export const createConversation = (data) => api.post('/conversations', data)
export const getMessages = (convId) => api.get(`/conversations/${convId}/messages`)
export const deleteConversation = (convId) => api.delete(`/conversations/${convId}`)

/**
 * 发送消息并获取 SSE 流式响应
 * @param {Object} data - { conversation_id, kb_id, message }
 * @param {Function} onChunk - 收到每个 token 时的回调
 * @param {Function} onSources - 收到来源信息时的回调
 * @param {Function} onDone - 完成时的回调
 * @param {Function} onError - 出错时的回调
 * @returns {Function} abort - 调用可中止请求
 */
export function chatStream(data, { onChunk, onSources, onDone, onError, onConversationId }) {
  const token = localStorage.getItem('token')
  const controller = new AbortController()
  let doneCalled = false

  const safeOnDone = (eventData) => {
    if (!doneCalled) {
      doneCalled = true
      onDone?.(eventData)
    }
  }

  const safeOnError = (err) => {
    if (!doneCalled) {
      doneCalled = true
      onError?.(err)
    }
  }

  fetch('/api/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${token}`,
      'Accept': 'text/event-stream',
    },
    body: JSON.stringify(data),
    signal: controller.signal,
    cache: 'no-cache',
  }).then(async (response) => {
    if (!response.ok) {
      const err = await response.json().catch(() => ({}))
      throw new Error(err.detail || '请求失败')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const eventData = JSON.parse(line.slice(6))
            switch (eventData.type) {
              case 'conversation':
                onConversationId?.(eventData.conversation_id)
                break
              case 'chunk':
                onChunk?.(eventData.content)
                break
              case 'sources':
                onSources?.(eventData.sources)
                break
              case 'done':
                safeOnDone(eventData)
                break
              case 'error':
                safeOnError(eventData.content)
                break
            }
          } catch (e) {
            // JSON parse error, skip
          }
        }
      }
    }

    // 处理 buffer 中剩余数据
    if (buffer.startsWith('data: ')) {
      try {
        const eventData = JSON.parse(buffer.slice(6))
        if (eventData.type === 'done') safeOnDone(eventData)
        else if (eventData.type === 'error') safeOnError(eventData.content)
      } catch (e) {}
    }
  }).catch((err) => {
    if (err.name !== 'AbortError') {
      console.error('Chat stream error:', err)
      safeOnError(err.message)
    } else {
      console.log('Chat stream aborted by user')
    }
  }).finally(() => {
    // 兜底：如果流结束但没有收到 done/error 事件，确保 UI 状态恢复
    safeOnDone()
  })

  return () => controller.abort()
}
