// 管理后台 API（仅管理员可访问）
import api from './index'

// 对话日志列表（分页 + 用户/时间筛选）
export const getAdminLogs = (params) => api.get('/admin/logs', { params })

// 单对话完整消息（tool_calls / token_count / sources）
export const getAdminLogDetail = (convId) => api.get(`/admin/logs/${convId}`)

// 系统设置（当前模型 / 白名单 / 飞书 bot 状态）
export const getAdminSettings = () => api.get('/admin/settings')

// 切换 LLM 模型
export const updateAdminSettings = (data) => api.post('/admin/settings', data)

// 飞书知识库绑定列表（按群 chat_id / 按人 open_id）
export const getAdminBindings = () => api.get('/admin/bindings')

// 新增/更新绑定（upsert：open_id 或 chat_id + kb_id）
export const createAdminBinding = (data) => api.post('/admin/bindings', data)

// 删除绑定
export const deleteAdminBinding = (id) => api.delete(`/admin/bindings/${id}`)

