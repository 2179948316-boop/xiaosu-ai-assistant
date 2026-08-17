<template>
  <div class="settings-page">
    <!-- 顶部导航 -->
    <header class="page-header">
      <div class="header-left">
        <el-button :icon="ArrowLeft" @click="$router.push('/admin/logs')" text>
          返回日志
        </el-button>
        <h1>系统设置</h1>
      </div>
    </header>

    <div class="settings-grid">
      <!-- LLM 模型 -->
      <el-card shadow="never" class="setting-card">
        <template #header>
          <div class="card-title">
            <el-icon color="#409eff"><Cpu /></el-icon>
            <span>LLM 模型</span>
          </div>
        </template>
        <div class="setting-row">
          <span class="setting-label">LLM 提供商</span>
          <el-tag size="small" :type="settings.llm_provider === 'minimax' ? 'success' : 'warning'">
            {{ settings.llm_provider === 'minimax' ? 'MiniMax' : 'DeepSeek' }}
          </el-tag>
        </div>
        <div class="setting-row">
          <span class="setting-label">切换提供商</span>
          <el-select
            v-model="selectedProvider"
            placeholder="选择提供商"
            style="width: 260px"
          >
            <el-option label="MiniMax" value="minimax" />
            <el-option label="DeepSeek" value="deepseek" />
          </el-select>
        </div>
        <div class="setting-row">
          <span class="setting-label">当前模型</span>
          <el-select
            v-model="selectedModel"
            placeholder="选择模型"
            style="width: 260px"
            :disabled="saving"
          >
            <el-option
              v-for="m in settings.model_whitelist"
              :key="m"
              :label="m + (m === settings.llm_model ? '（当前）' : '')"
              :value="m"
            />
          </el-select>
        </div>
        <div class="setting-row">
          <span class="setting-label"></span>
          <el-button
            type="primary"
            :loading="saving"
            :disabled="!selectedModel || (selectedModel === settings.llm_model && selectedProvider === settings.llm_provider)"
            @click="handleSaveModel"
          >
            保存并切换
          </el-button>
        </div>
        <p class="card-tip">
          切换后写入 backend/.env（{{ selectedProvider === 'minimax' ? 'MINIMAX_LLM_MODEL' : 'DEEPSEEK_LLM_MODEL' }}），
          重启服务依然生效；白名单可在 .env 的 LLM_MODEL_WHITELIST 中调整。
        </p>
      </el-card>

      <!-- 飞书机器人 -->
      <el-card shadow="never" class="setting-card">
        <template #header>
          <div class="card-title">
            <el-icon color="#00b96b"><ChatDotRound /></el-icon>
            <span>飞书机器人</span>
          </div>
        </template>
        <div class="setting-row">
          <span class="setting-label">连接状态</span>
          <el-tag :type="botConnected ? 'success' : 'danger'" effect="dark">
            {{ botConnected ? '在线（长连接）' : '离线' }}
          </el-tag>
        </div>
        <div class="setting-row" v-if="botConnected">
          <span class="setting-label">进程 PID</span>
          <code class="mono">{{ settings.bot.pid }}</code>
        </div>
        <div class="setting-row" v-if="botConnected">
          <span class="setting-label">最后心跳</span>
          <span class="setting-value">{{ formatDate(settings.bot.heartbeat_at) }}</span>
        </div>
        <div class="setting-row">
          <span class="setting-label">应用配置</span>
          <el-tag size="small" :type="settings.feishu.configured ? 'success' : 'danger'" effect="plain">
            {{ settings.feishu.configured ? 'App ID 已配置' : '未配置凭据' }}
          </el-tag>
          <span v-if="settings.feishu.app_id" class="setting-value mono">{{ settings.feishu.app_id }}</span>
        </div>
        <p class="card-tip">
          心跳每 15 秒由 bot 进程写入一次，超过 90 秒未更新即判定离线。
          启动方式：<code>uv run python bot_service.py</code>
        </p>
      </el-card>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ArrowLeft, Cpu, ChatDotRound } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getAdminSettings, updateAdminSettings } from '../api/admin'

const settings = ref({ llm_provider: '', llm_model: '', model_whitelist: [], feishu: {}, bot: {} })
const selectedModel = ref('')
const selectedProvider = ref('minimax')
const saving = ref(false)

const botConnected = computed(() => !!settings.value.bot?.connected)

async function loadSettings() {
  try {
    settings.value = await getAdminSettings()
    selectedModel.value = settings.value.llm_model
    selectedProvider.value = settings.value.llm_provider
  } catch (e) {}
}

async function handleSaveModel() {
  saving.value = true
  try {
    const res = await updateAdminSettings({
      llm_model: selectedModel.value,
      llm_provider: selectedProvider.value,
    })
    ElMessage.success(`已切换 ${res.llm_provider === 'minimax' ? 'MiniMax' : 'DeepSeek'}：${res.llm_model}`)
    await loadSettings()
  } catch (e) {
  } finally {
    saving.value = false
  }
}

function formatDate(value) {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 19)
}

onMounted(loadSettings)
</script>

<style scoped>
.settings-page {
  padding: 20px;
  height: 100%;
  overflow-y: auto;
  background: #f5f7fa;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-left h1 {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
}

.settings-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 16px;
  max-width: 960px;
}

.setting-card :deep(.el-card__header) {
  padding: 14px 20px;
}

.card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  color: #303133;
}

.setting-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.setting-label {
  width: 90px;
  flex-shrink: 0;
  font-size: 14px;
  color: #606266;
}

.setting-value {
  font-size: 14px;
  color: #303133;
}

.mono {
  font-family: Consolas, monospace;
  font-size: 13px;
  background: #f0f2f5;
  padding: 2px 6px;
  border-radius: 4px;
}

.card-tip {
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
  border-top: 1px dashed #e4e7ed;
  padding-top: 12px;
  margin: 8px 0 0;
}
</style>
