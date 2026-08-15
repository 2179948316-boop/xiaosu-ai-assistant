<template>
  <div class="kb-selector">
    <el-select
      :model-value="modelValue"
      placeholder="选择知识库"
      size="small"
      style="width: 100%"
      @update:model-value="$emit('update:modelValue', $event)"
    >
      <el-option
        v-for="kb in knowledgeBases"
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
      @click="showCreate = true"
      style="margin-left: 8px; flex-shrink: 0"
    />

    <!-- 创建知识库弹窗 -->
    <el-dialog v-model="showCreate" title="创建知识库" width="460px">
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
              v-for="org in organizations"
              :key="org.id"
              :label="org.name"
              :value="org.id"
            />
          </el-select>
          <div class="form-tip">选择组织后，该组织所有成员均可访问此知识库</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="handleCreate" :loading="creating">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { createKnowledgeBase } from '../api/document'

const props = defineProps({
  // 当前选中的知识库 ID（v-model）
  modelValue: { type: Number, default: null },
  // 当前空间下可见的知识库列表
  knowledgeBases: { type: Array, default: () => [] },
  // 创建知识库时可选的组织列表
  organizations: { type: Array, default: () => [] },
  // 当前工作空间 ID，作为新建知识库的默认归属
  defaultOrgId: { type: Number, default: null },
})

const emit = defineEmits(['update:modelValue', 'created'])

const showCreate = ref(false)
const creating = ref(false)
const newKb = ref({ name: '', description: '', org_id: null })

async function handleCreate() {
  if (!newKb.value.name.trim()) {
    ElMessage.warning('请输入知识库名称')
    return
  }
  creating.value = true
  try {
    const payload = {
      name: newKb.value.name,
      description: newKb.value.description,
      org_id: newKb.value.org_id ?? props.defaultOrgId ?? null,
    }
    const kb = await createKnowledgeBase(payload)
    showCreate.value = false
    newKb.value = { name: '', description: '', org_id: null }
    ElMessage.success('知识库创建成功')
    emit('created', kb)
  } catch (e) {} finally {
    creating.value = false
  }
}
</script>

<style scoped>
.kb-selector {
  padding: 12px 16px;
  display: flex;
  align-items: center;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
  line-height: 1.4;
}
</style>
