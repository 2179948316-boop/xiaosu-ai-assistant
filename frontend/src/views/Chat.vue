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
    <aside :class="['sidebar', { 'sidebar-visible': isMobile && sidebarVisible }]">
      <div class="sidebar-header">
        <el-icon :size="24" color="#fff"><DataAnalysis /></el-icon>
        <span class="sidebar-title">知识库问答</span>
      </div>

      <!-- 组织/空间切换 -->
      <div class="org-selector">
        <el-select
          v-model="currentOrgId"
          placeholder="工作空间"
          size="small"
          style="width: 100%"
          @change="handleOrgChange"
        >
          <el-option label="个人空间" :value="null" />
          <el-option
            v-for="org in organizations"
            :key="org.id"
            :label="org.name"
            :value="org.id"
          >
            <span>{{ org.name }}</span>
            <el-tag size="small" type="success" style="float: right">{{ org.member_count }} 人</el-tag>
          </el-option>
        </el-select>
        <el-button
          size="small"
          :icon="Setting"
          circle
          @click="showOrgManage = true"
          style="margin-left: 8px; flex-shrink: 0"
          title="组织管理"
        />
      </div>

      <!-- 知识库选择 -->
      <div class="kb-selector">
        <el-select
          v-model="selectedKbId"
          placeholder="选择知识库"
          size="small"
          style="width: 100%"
          @change="handleKbChange"
        >
          <el-option
            v-for="kb in filteredKnowledgeBases"
            :key="kb.id"
            :label="kb.name"
            :value="kb.id"
          >
            <span>{{ kb.name }}</span>
            <el-tag v-if="kb.org_name" size="small" type="success" style="float: right; margin-left: 4px">{{ kb.org_name }}</el-tag>
            <el-tag size="small" type="info" style="float: right">{{ kb.document_count }} 文档</el-tag>
          </el-option>
        </el-select>
        <el-button
          type="primary"
          size="small"
          :icon="Plus"
          circle
          @click="showCreateKb = true"
          style="margin-left: 8px; flex-shrink: 0"
        />
      </div>

      <!-- 新建对话 -->
      <el-button
        type="primary"
        :icon="EditPen"
        @click="handleNewChat"
        class="new-chat-btn"
      >
        新建对话
      </el-button>

      <!-- 对话列表 -->
      <div class="conversation-list">
        <div
          v-for="conv in conversations"
          :key="conv.id"
          :class="['conversation-item', { active: conv.id === currentConvId }]"
          @click="handleSelectConversation(conv)"
        >
          <el-icon><ChatDotRound /></el-icon>
          <span class="conv-title">{{ conv.title || '新对话' }}</span>
          <el-icon
            class="conv-delete"
            @click.stop="handleDeleteConversation(conv.id)"
          >
            <Delete />
          </el-icon>
        </div>
        <div v-if="conversations.length === 0" class="no-conversations">
          暂无对话记录
        </div>
      </div>

      <!-- 底部操作 -->
      <div class="sidebar-footer">
        <el-button text @click="goToDocuments" class="footer-btn">
          <el-icon><Document /></el-icon>
          文档管理
        </el-button>
        <el-button text @click="handleLogout" class="footer-btn">
          <el-icon><SwitchButton /></el-icon>
          退出登录
        </el-button>
      </div>
    </aside>

    <!-- 聊天主区域 -->
    <main class="chat-main">
      <!-- 消息列表 -->
      <div class="messages-container" ref="messagesContainer">
        <!-- 欢迎页面 -->
        <div v-if="messages.length === 0 && !isStreaming" class="welcome">
          <el-icon :size="64" color="#c0c4cc"><ChatLineSquare /></el-icon>
          <h2>欢迎使用知识库问答系统</h2>
          <p>选择一个知识库，然后输入您的问题</p>
          <div class="welcome-tips">
            <div class="tip-card" @click="sendQuickQuestion('请帮我总结知识库中的主要内容')">
              <el-icon><Files /></el-icon>
              <span>总结知识库主要内容</span>
            </div>
            <div class="tip-card" @click="sendQuickQuestion('知识库中有哪些关键概念和定义？')">
              <el-icon><Search /></el-icon>
              <span>查找关键概念和定义</span>
            </div>
            <div class="tip-card" @click="sendQuickQuestion('请列出知识库中提到的重要流程和规范')">
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

      <!-- 输入区域 -->
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
            @click="handleStopGenerate"
            circle
          />
          <!-- 非流式时显示发送按钮 -->
          <el-button
            v-else
            type="primary"
            :icon="Promotion"
            :disabled="!inputMessage.trim() || !selectedKbId"
            @click="handleSend"
            circle
          />
        </div>
        <div class="input-hint">
          <span v-if="!selectedKbId" class="hint-warning">请先选择一个知识库</span>
          <span v-else class="hint-info">当前知识库: {{ currentKbName }}</span>
        </div>
      </div>
    </main>

    <!-- 创建知识库弹窗 -->
    <el-dialog v-model="showCreateKb" title="创建知识库" width="460px">
      <el-form :model="newKb" label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="newKb.name" placeholder="输入知识库名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="newKb.description"
            type="textarea"
            :rows="3"
            placeholder="可选，描述知识库用途"
          />
        </el-form-item>
        <el-form-item label="所属空间">
          <el-select v-model="newKb.org_id" placeholder="个人空间（私有）" clearable style="width: 100%">
            <el-option label="个人空间（仅自己可见）" :value="null" />
            <el-option
              v-for="org in adminOrganizations"
              :key="org.id"
              :label="org.name"
              :value="org.id"
            />
          </el-select>
          <div class="form-tip">选择组织后，该组织所有成员均可访问此知识库</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateKb = false">取消</el-button>
        <el-button type="primary" @click="handleCreateKb" :loading="creatingKb">创建</el-button>
      </template>
    </el-dialog>

    <!-- 组织管理弹窗 -->
    <el-dialog v-model="showOrgManage" title="组织管理" width="560px">
      <!-- 创建组织 -->
      <div class="org-create-section">
        <el-input
          v-model="newOrgName"
          placeholder="输入新组织名称"
          style="width: 240px"
          size="default"
        />
        <el-button type="primary" @click="handleCreateOrg" :loading="creatingOrg" style="margin-left: 12px">
          创建组织
        </el-button>
      </div>

      <el-divider />

      <!-- 组织列表 + 成员管理 -->
      <div v-if="organizations.length === 0" style="text-align: center; color: #909399; padding: 20px 0">
        暂未加入任何组织
      </div>
      <div v-for="org in organizations" :key="org.id" class="org-item">
        <div class="org-item-header">
          <span class="org-item-name">{{ org.name }}</span>
          <el-tag size="small">{{ org.member_count }} 人</el-tag>
          <el-button
            v-if="org.owner_id === userStore.user?.id"
            type="danger"
            size="small"
            text
            @click="handleDeleteOrg(org)"
          >
            解散
          </el-button>
        </div>

        <!-- 展开成员列表 -->
        <div v-if="expandedOrgId === org.id" class="org-members">
          <div v-for="m in orgMembers" :key="m.id" class="member-row">
            <span>{{ m.username }}</span>
            <el-tag size="small" :type="m.role === 'admin' ? 'warning' : 'info'">
              {{ m.role === 'admin' ? '管理员' : '成员' }}
            </el-tag>
            <el-button
              v-if="m.role !== 'admin' || m.user_id !== userStore.user?.id"
              type="danger"
              size="small"
              text
              :icon="Delete"
              @click="handleRemoveMember(org.id, m)"
            />
          </div>
          <!-- 添加成员 -->
          <div class="add-member-row">
            <el-input v-model="newMemberUsername" placeholder="输入用户名" size="small" style="width: 160px" />
            <el-button size="small" type="primary" @click="handleAddMember(org.id)" style="margin-left: 8px">
              邀请
            </el-button>
          </div>
        </div>

        <el-button
          text
          size="small"
          @click="toggleOrgExpand(org.id)"
          style="margin-top: 4px"
        >
          {{ expandedOrgId === org.id ? '收起成员' : '查看成员' }}
        </el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  DataAnalysis, Plus, EditPen, ChatDotRound, Delete,
  Document, SwitchButton, User, Monitor, Promotion,
  ChatLineSquare, Files, Search, List,
  Fold, CloseBold, CopyDocument, Setting
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { marked } from 'marked'
import { useUserStore } from '../stores/user'
import { useChatStore } from '../stores/chat'
import { getKnowledgeBases, createKnowledgeBase } from '../api/document'
import { getConversations, getMessages, deleteConversation, chatStream } from '../api/chat'
import {
  getOrganizations, createOrganization, deleteOrganization,
  getOrgMembers, addOrgMember, removeOrgMember
} from '../api/organization'

const router = useRouter()
const userStore = useUserStore()
const chatStore = useChatStore()

// 状态
const messagesContainer = ref(null)
const inputMessage = ref('')
const selectedKbId = ref(null)
const knowledgeBases = ref([])
const conversations = ref([])
const currentConvId = ref(null)
const isStreaming = ref(false)
const streamingContent = ref('')
const currentSources = ref([])
const showCreateKb = ref(false)
const creatingKb = ref(false)
const newKb = ref({ name: '', description: '', org_id: null })
const isMobile = ref(false)
const sidebarVisible = ref(false)
let abortStream = null

// 组织相关状态
const currentOrgId = ref(null)
const organizations = ref([])
const showOrgManage = ref(false)
const creatingOrg = ref(false)
const newOrgName = ref('')
const expandedOrgId = ref(null)
const orgMembers = ref([])
const newMemberUsername = ref('')

const messages = computed(() => chatStore.messages)
const currentKbName = computed(() => {
  const kb = knowledgeBases.value.find(k => k.id === selectedKbId.value)
  return kb ? kb.name : ''
})

// 按当前空间过滤知识库
const filteredKnowledgeBases = computed(() => {
  if (currentOrgId.value === null) {
    // 个人空间：只显示个人知识库
    return knowledgeBases.value.filter(kb => !kb.org_id)
  }
  // 组织空间：显示该组织的知识库
  return knowledgeBases.value.filter(kb => kb.org_id === currentOrgId.value)
})

// 用户担任 admin 的组织（用于创建知识库时选择）
const adminOrganizations = computed(() => {
  return organizations.value
})

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

// 加载知识库列表
async function loadKnowledgeBases() {
  try {
    knowledgeBases.value = await getKnowledgeBases()
    if (knowledgeBases.value.length > 0 && !selectedKbId.value) {
      selectedKbId.value = knowledgeBases.value[0].id
    }
  } catch (e) {}
}

// 加载对话列表
async function loadConversations() {
  try {
    conversations.value = await getConversations()
  } catch (e) {}
}

// 加载组织列表
async function loadOrganizations() {
  try {
    organizations.value = await getOrganizations()
  } catch (e) {}
}

// 切换工作空间
function handleOrgChange() {
  // 切换空间后重置知识库选择
  selectedKbId.value = null
  const filtered = filteredKnowledgeBases.value
  if (filtered.length > 0) {
    selectedKbId.value = filtered[0].id
  }
}

// 选择知识库
function handleKbChange(kbId) {
  selectedKbId.value = kbId
}

// 创建知识库
async function handleCreateKb() {
  if (!newKb.value.name.trim()) {
    ElMessage.warning('请输入知识库名称')
    return
  }
  creatingKb.value = true
  try {
    const payload = {
      name: newKb.value.name,
      description: newKb.value.description,
      org_id: newKb.value.org_id ?? currentOrgId.value ?? null,
    }
    const kb = await createKnowledgeBase(payload)
    knowledgeBases.value.unshift(kb)
    selectedKbId.value = kb.id
    showCreateKb.value = false
    newKb.value = { name: '', description: '', org_id: null }
    ElMessage.success('知识库创建成功')
  } catch (e) {} finally {
    creatingKb.value = false
  }
}

// 新建对话
async function handleNewChat() {
  // 中断正在进行的流式请求
  if (abortStream) {
    abortStream()
    abortStream = null
  }
  // 重置本地流式状态
  isStreaming.value = false
  streamingContent.value = ''
  currentSources.value = []
  // 重置对话状态
  chatStore.resetChat()
  currentConvId.value = null
  // 刷新对话列表，确保上一个对话已保存
  await loadConversations()
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

  currentConvId.value = conv.id
  chatStore.currentConversationId = conv.id
  if (isMobile.value) sidebarVisible.value = false
  try {
    const msgs = await getMessages(conv.id)
    chatStore.setMessages(msgs)
    scrollToBottom()
  } catch (e) {}
}

// 删除对话
async function handleDeleteConversation(convId) {
  try {
    await ElMessageBox.confirm('确定删除该对话？', '提示', { type: 'warning' })
    await deleteConversation(convId)
    conversations.value = conversations.value.filter(c => c.id !== convId)
    if (currentConvId.value === convId) {
      chatStore.resetChat()
      currentConvId.value = null
    }
    ElMessage.success('对话已删除')
  } catch (e) {}
}

// 发送消息
async function handleSend() {
  const message = inputMessage.value.trim()
  if (!message || !selectedKbId.value || isStreaming.value) return

  // 添加用户消息到界面
  chatStore.addMessage({
    role: 'user',
    content: message,
    created_at: new Date().toISOString(),
  })
  inputMessage.value = ''
  scrollToBottom()

  // 开始流式响应
  isStreaming.value = true
  streamingContent.value = ''
  currentSources.value = []

  abortStream = chatStream(
    {
      conversation_id: currentConvId.value,
      kb_id: selectedKbId.value,
      message,
    },
    {
      onConversationId: (convId) => {
        currentConvId.value = convId
        chatStore.currentConversationId = convId
        // 乐观更新：立即将新对话加入列表（不等后端 commit 完成）
        const exists = conversations.value.some(c => c.id === convId)
        if (!exists) {
          conversations.value.unshift({
            id: convId,
            title: message.slice(0, 50),
            kb_id: selectedKbId.value,
            updated_at: new Date().toISOString(),
          })
        }
        // 延迟刷新确保与后端同步
        setTimeout(() => loadConversations(), 500)
      },
      onChunk: (token) => {
        streamingContent.value += token
        scrollToBottom()
      },
      onSources: (sources) => {
        currentSources.value = sources
        scrollToBottom()
      },
      onDone: () => {
        if (streamingContent.value) {
          chatStore.addMessage({
            role: 'assistant',
            content: streamingContent.value,
            sources: currentSources.value,
            created_at: new Date().toISOString(),
          })
        }
        streamingContent.value = ''
        currentSources.value = []
        isStreaming.value = false
        scrollToBottom()
      },
      onError: (err) => {
        ElMessage.error(err || '生成回复失败')
        isStreaming.value = false
      },
    }
  )
}

// 快捷问题
function sendQuickQuestion(question) {
  inputMessage.value = question
  handleSend()
}

// 键盘事件
function handleKeyDown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
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
      created_at: new Date().toISOString(),
    })
  }
  streamingContent.value = ''
  currentSources.value = []
  isStreaming.value = false
}

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

// 移动端检测
function checkMobile() {
  isMobile.value = window.innerWidth < 768
  if (!isMobile.value) {
    sidebarVisible.value = false
  }
}

function handleResize() {
  checkMobile()
}

// ============ 组织管理 ============

async function handleCreateOrg() {
  if (!newOrgName.value.trim()) {
    ElMessage.warning('请输入组织名称')
    return
  }
  creatingOrg.value = true
  try {
    await createOrganization({ name: newOrgName.value.trim() })
    newOrgName.value = ''
    await loadOrganizations()
    ElMessage.success('组织创建成功')
  } catch (e) {} finally {
    creatingOrg.value = false
  }
}

async function handleDeleteOrg(org) {
  try {
    await ElMessageBox.confirm(`确定解散组织「${org.name}」？该操作不可恢复。`, '警告', { type: 'warning' })
    await deleteOrganization(org.id)
    await loadOrganizations()
    if (currentOrgId.value === org.id) {
      currentOrgId.value = null
      handleOrgChange()
    }
    ElMessage.success('组织已解散')
  } catch (e) {}
}

async function toggleOrgExpand(orgId) {
  if (expandedOrgId.value === orgId) {
    expandedOrgId.value = null
    orgMembers.value = []
    return
  }
  expandedOrgId.value = orgId
  try {
    orgMembers.value = await getOrgMembers(orgId)
  } catch (e) {
    orgMembers.value = []
  }
}

async function handleAddMember(orgId) {
  if (!newMemberUsername.value.trim()) {
    ElMessage.warning('请输入用户名')
    return
  }
  try {
    await addOrgMember(orgId, { username: newMemberUsername.value.trim() })
    newMemberUsername.value = ''
    orgMembers.value = await getOrgMembers(orgId)
    await loadOrganizations()
    ElMessage.success('成员已添加')
  } catch (e) {}
}

async function handleRemoveMember(orgId, member) {
  try {
    await ElMessageBox.confirm(`确定移除成员「${member.username}」？`, '提示', { type: 'warning' })
    await removeOrgMember(orgId, member.user_id)
    orgMembers.value = await getOrgMembers(orgId)
    await loadOrganizations()
    ElMessage.success('成员已移除')
  } catch (e) {}
}

// 跳转文档管理
function goToDocuments() {
  router.push('/documents')
}

// 退出登录
function handleLogout() {
  userStore.logout()
}

// 监听消息变化滚动到底部
watch(messages, scrollToBottom, { deep: true })

onMounted(async () => {
  checkMobile()
  window.addEventListener('resize', handleResize)
  await Promise.all([loadKnowledgeBases(), loadConversations(), loadOrganizations()])
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})
</script>

<style scoped>
.chat-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

/* ===== 侧边栏 ===== */
.sidebar {
  width: 280px;
  background: #1a1a2e;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
}

.sidebar-header {
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.sidebar-title {
  color: #fff;
  font-size: 18px;
  font-weight: 600;
}

.kb-selector {
  padding: 12px 16px;
  display: flex;
  align-items: center;
}

.org-selector {
  padding: 12px 16px 0;
  display: flex;
  align-items: center;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  line-height: 1.4;
}

.org-create-section {
  display: flex;
  align-items: center;
}

.org-item {
  padding: 12px;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  margin-bottom: 12px;
}

.org-item-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.org-item-name {
  font-weight: 600;
  font-size: 15px;
}

.org-members {
  margin-top: 8px;
  padding: 8px;
  background: #f5f7fa;
  border-radius: 6px;
}

.member-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 4px;
}

.member-row span {
  flex: 1;
}

.add-member-row {
  display: flex;
  align-items: center;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #dcdfe6;
}

.new-chat-btn {
  margin: 0 16px 12px;
}

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 0 8px;
}

.conversation-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  color: #b0b0c0;
  margin-bottom: 2px;
  transition: all 0.2s;
}

.conversation-item:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.conversation-item.active {
  background: rgba(64, 158, 255, 0.2);
  color: #409eff;
}

.conv-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
}

.conv-delete {
  opacity: 0;
  transition: opacity 0.2s;
  font-size: 14px;
}

.conversation-item:hover .conv-delete {
  opacity: 1;
}

.no-conversations {
  text-align: center;
  color: #666;
  padding: 32px 0;
  font-size: 14px;
}

.sidebar-footer {
  padding: 12px 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.footer-btn {
  width: 100%;
  justify-content: flex-start;
  color: #b0b0c0 !important;
}

.footer-btn:hover {
  color: #fff !important;
}

/* ===== 聊天主区域 ===== */
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
  min-width: 0;
}

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

/* 输入区域 */
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

/* ===== 响应式适配 ===== */
@media (max-width: 768px) {
  .chat-layout {
    flex-direction: column;
    padding-top: 52px;
  }

  .sidebar {
    position: fixed;
    top: 52px;
    left: 0;
    bottom: 0;
    width: 280px;
    z-index: 200;
    transform: translateX(-100%);
    transition: transform 0.3s ease;
  }

  .sidebar.sidebar-visible {
    transform: translateX(0);
  }

  .chat-main {
    width: 100%;
    height: calc(100vh - 52px);
  }

  .messages-container {
    padding: 16px;
  }

  .message {
    max-width: 100%;
  }

  .input-area {
    padding: 12px 16px;
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
