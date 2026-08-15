<template>
  <el-dialog :model-value="modelValue" title="组织管理" width="560px" @update:model-value="$emit('update:modelValue', $event)">
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
          v-if="org.owner_id === currentUserId"
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
            v-if="m.role !== 'admin' || m.user_id !== currentUserId"
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
</template>

<script setup>
import { ref } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createOrganization, deleteOrganization,
  getOrgMembers, addOrgMember, removeOrgMember
} from '../api/organization'

const props = defineProps({
  // 弹窗可见性（v-model）
  modelValue: { type: Boolean, default: false },
  // 我加入的组织列表
  organizations: { type: Array, default: () => [] },
  // 当前登录用户 ID（用于判断解散权限）
  currentUserId: { type: Number, default: null },
})

const emit = defineEmits(['update:modelValue', 'changed', 'org-deleted'])

const creatingOrg = ref(false)
const newOrgName = ref('')
const expandedOrgId = ref(null)
const orgMembers = ref([])
const newMemberUsername = ref('')

async function handleCreateOrg() {
  if (!newOrgName.value.trim()) {
    ElMessage.warning('请输入组织名称')
    return
  }
  creatingOrg.value = true
  try {
    await createOrganization({ name: newOrgName.value.trim() })
    newOrgName.value = ''
    ElMessage.success('组织创建成功')
    emit('changed')
  } catch (e) {} finally {
    creatingOrg.value = false
  }
}

async function handleDeleteOrg(org) {
  try {
    await ElMessageBox.confirm(`确定解散组织「${org.name}」？该操作不可恢复。`, '警告', { type: 'warning' })
    await deleteOrganization(org.id)
    ElMessage.success('组织已解散')
    emit('org-deleted', org.id)
    emit('changed')
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
    ElMessage.success('成员已添加')
    emit('changed')
  } catch (e) {}
}

async function handleRemoveMember(orgId, member) {
  try {
    await ElMessageBox.confirm(`确定移除成员「${member.username}」？`, '提示', { type: 'warning' })
    await removeOrgMember(orgId, member.user_id)
    orgMembers.value = await getOrgMembers(orgId)
    ElMessage.success('成员已移除')
    emit('changed')
  } catch (e) {}
}
</script>

<style scoped>
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
</style>
