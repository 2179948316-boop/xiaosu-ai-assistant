<template>
  <aside :class="['sidebar', { 'sidebar-visible': isMobile && visible }]">
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
    <KbSelector
      v-model="selectedKbId"
      :knowledge-bases="filteredKnowledgeBases"
      :organizations="organizations"
      :default-org-id="currentOrgId"
      @created="handleKbCreated"
    />

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
        @click="$emit('select-conversation', conv)"
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

    <!-- 组织管理弹窗 -->
    <OrgManage
      v-model="showOrgManage"
      :organizations="organizations"
      :current-user-id="userStore.user?.id"
      @changed="loadOrganizations"
      @org-deleted="handleOrgDeleted"
    />
  </aside>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  DataAnalysis, EditPen, ChatDotRound, Delete,
  Document, SwitchButton, Setting
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '../stores/user'
import { getKnowledgeBases } from '../api/document'
import { getConversations, deleteConversation } from '../api/chat'
import { getOrganizations } from '../api/organization'
import KbSelector from './KbSelector.vue'
import OrgManage from './OrgManage.vue'

const props = defineProps({
  // 是否移动端（控制侧边栏抽屉样式）
  isMobile: { type: Boolean, default: false },
  // 移动端抽屉是否展开
  visible: { type: Boolean, default: false },
  // 当前激活的对话 ID（用于高亮）
  currentConvId: { type: Number, default: null },
})

const emit = defineEmits(['kb-change', 'new-chat', 'select-conversation', 'conversation-deleted'])

const router = useRouter()
const userStore = useUserStore()

// 状态
const selectedKbId = ref(null)
const knowledgeBases = ref([])
const conversations = ref([])
const currentOrgId = ref(null)
const organizations = ref([])
const showOrgManage = ref(false)

// 按当前空间过滤知识库
const filteredKnowledgeBases = computed(() => {
  if (currentOrgId.value === null) {
    // 个人空间：只显示个人知识库
    return knowledgeBases.value.filter(kb => !kb.org_id)
  }
  // 组织空间：显示该组织的知识库
  return knowledgeBases.value.filter(kb => kb.org_id === currentOrgId.value)
})

// 选中知识库变化时，向父组件同步完整知识库对象
watch(selectedKbId, (id) => {
  const kb = knowledgeBases.value.find(k => k.id === id) || null
  emit('kb-change', kb)
})

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

// 组织被解散：若为当前空间则切回个人空间
function handleOrgDeleted(orgId) {
  if (currentOrgId.value === orgId) {
    currentOrgId.value = null
    handleOrgChange()
  }
}

// 新建知识库成功后加入列表并选中
function handleKbCreated(kb) {
  knowledgeBases.value.unshift(kb)
  selectedKbId.value = kb.id
}

// 新建对话（流式中断由父组件处理）
async function handleNewChat() {
  emit('new-chat')
  await loadConversations()
}

// 删除对话
async function handleDeleteConversation(convId) {
  try {
    await ElMessageBox.confirm('确定删除该对话？', '提示', { type: 'warning' })
    await deleteConversation(convId)
    conversations.value = conversations.value.filter(c => c.id !== convId)
    emit('conversation-deleted', convId)
    ElMessage.success('对话已删除')
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

onMounted(() => {
  Promise.all([loadKnowledgeBases(), loadConversations(), loadOrganizations()])
})

// 供父组件在流式回调中维护对话列表
function addConversation(conv) {
  const exists = conversations.value.some(c => c.id === conv.id)
  if (!exists) {
    conversations.value.unshift(conv)
  }
}

defineExpose({
  addConversation,
  refreshConversations: loadConversations,
})
</script>

<style scoped>
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

.org-selector {
  padding: 12px 16px 0;
  display: flex;
  align-items: center;
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

/* ===== 响应式适配 ===== */
@media (max-width: 768px) {
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
}
</style>
